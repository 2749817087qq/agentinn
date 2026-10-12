# free-model-relay v5.5.0 — 技术设计（Phase 2 SPEC）

> Change: `relay-v550-program-cache-scanner`
> 模式：`standard`（复杂度评分 7）
> 基线 git sha：`829fc03`（用户上报 v5.4 HEAD；本环境非沙箱 git 解析不一致，待 Deliver 复验）

## Context

当前 relay 的免费时段判定依赖 SKILL.md 与 `pick_model.py` 中**硬编码**的
`FREE_WINDOW_DEFAULT = {since:"2026-09-11", until:"2026-10-10", start_hour:23, end_hour:8}`，
并把 hy3 系与 hy4 系套用**同一** 23:00–08:00 窗口。2026-10-11 实测解剖双根程序缓存
`~/.workbuddy/cache/acc-product-config-v3.json` 与 `~/.workbuddy-ai/cache/acc-product-config-v3.json`
发现这是错的：

- hy3 / hy3-b / hy3-c：**全天免费**（base credits `x0.00`，无时段限制）；
- hy4-preview / hy4-preview-dev：base `x0.29` + promo `0x`，**仅夜间 23:00–08:00 免费**；
- glm-5.2：夜间 `0.50x`；deepseek-v4 系：非高峰 `0.50x`；
- AI 根额外：`deepseek-v4.1-flash` base `x0.00` 免费；
- 全部 7 条 `modelPromotions` 的 `validUntil = 2026-11-01`（非硬编码的 10-10）。

该缓存是程序启动时从 `www.workbuddy.cn/v3/config` **自动拉取并缓存**的权威数据源，
字段含 `models[].credits` 与 `modelPromotions[]`（modelIds / discount.discountedCredits /
schedule.{validFrom,validUntil,daily[]}），**零 API key、零硬编码日期**。

本变更用「启动扫描程序缓存」替代硬编码窗口，让免费/折扣清单自动跟随平台活动。

### 现有代码锚点（避免 design/实现矛盾）

| 现有符号 | 位置 | 作用 |
|---------|------|------|
| `FREE_WINDOW_DEFAULT` | L109 | 硬编码兜底窗口（C3 移除对象） |
| `is_free_window(model_id, now)` | L473 | 时段判定，调 `_effective_free_window` |
| `resolve_source(source_arg)` | L1379 | `auto` 调 `is_free_window()` 决定 `all`/`custom` |
| `load_models(source)` | 多处 | 候选集来源（`all`=平台+声明，`custom`=仅声明） |
| `cmd_next(args)` | L1742 | `resolve_source`→`load_models`→`filter_available`→轮询选模 |
| `load_declared_models()` | L1303 | 读 `models.json` 的 BYOK 自定义模型（C4 兜底源） |
| `MODELS_JSON` | L53 | 固定 `~/.workbuddy/models.json`（C5 回退 + 多根适配注意点） |

## Decisions

### 1. 新增 `scan_program_config()` — 双根缓存扫描器（对应 C1）

**方案**：新增模块级函数 `scan_program_config(roots=None, now=None) -> ScanResult`。
- `roots`：缓存目录列表，默认 `["~/.workbuddy/cache", "~/.workbuddy-ai/cache"]`（**双根适配**，见约束）。
- 逐根读取 `acc-product-config-v3.json`：
  - 文件缺失 → 该根记 `warning` 并跳过（**不抛异常、不静默置空**）；
  - JSON 解析失败 / 顶层非 dict → 该根记 `warning` 并跳过；
  - 字段缺失（`models` / `modelPromotions`）→ 该根仅产出可得部分，缺字段模型记 `degraded`。
- `effective` 计算：`base = parse_credits(m.credits)`（解析 `"x0.00"`→`0.0`）；
  对每个 active promotion（`validFrom ≤ now ≤ validUntil` 且 `now` 时刻落在 `daily[{start,end}]`
  窗口内，含跨午夜 `start>end` 处理），`factor = parse_credits(discount.discountedCredits)`
  （如 `"x0.50"`→`0.5`）；`effective = base * factor`（当 active 时；无 active promo 则 `effective = base`）。
- 输出每条：`{id, base_credits, effective_credits, free_now (effective==0),
  window ({"start","end"} 或 null), valid_until, source_root}`。
- 双根合并：按 `id` 合并；同 id 在两根都存在时取**更低 effective**（更保守，避免把收费当免费）。

**为什么**：缓存是权威、零 API key 数据源；双根合并保证 WorkBuddy 根 + AI 根的程序模型都被纳入候选（SC6）。

**备选方案及排除原因**：
- 备选 A：只扫单根 → 排除：两根是独立程序、目录不同，漏扫会丢 AI 根 `deepseek-v4.1-flash` 等免费模型（SC6）。
- 备选 B：运行时调 `www.workbuddy.cn/v3/config` 接口 → 排除：违反「零 API key / 只读本地缓存」约束，且引入网络依赖与静默失败面。

### 2. 候选池重写 — `build_free_candidate_pool()`（对应 C2，映射 proposal 的 `build_candidate_pool`）

**方案**：新增 `build_free_candidate_pool(now=None) -> list[str]`，作为 `cmd_next` 候选集的**首选来源**：
- 调 `scan_program_config()` 取 `free_now=True` 的模型 id → 默认候选集（**裸 id**：`hy3` / `hy4-preview` / `glm-5.2` / `deepseek-v4` 系等）；
- **BYOK `custom-local:*` 退出默认路径**：仅当扫描器产出为空（无任何当前免费模型）时，才回退到 `load_declared_models()`（BYOK 裸 id），并在输出中标注 `source="byok_fallback"`；调用方对 BYOK 项加 `custom-local:` 前缀（见 Decision 4）。
- `cmd_next` 将 `load_models(resolve_source(...))` 改为优先 `build_free_candidate_pool()`，再叠加 `filter_available` 的白名单/限流过滤。

**为什么**：候选池默认只用程序侧免费/折扣裸 id，契合 v5.5.0 用户定调；BYOK 仅兜底，彻底消除 10-11「同名劫持 + 429」两坑对默认路线的侵扰。

**备选方案及排除原因**：
- 备选 A：保留 `resolve_source("auto")` 的 `all`/`custom` 二分 → 排除：该二分仍依赖 `is_free_window()` 硬编码窗口（C3 要删），且无法表达「折扣 0.5x」这类非 0 非全价的中间态。

### 3. 移除硬编码窗口，改为消费扫描器（对应 C3）

**方案**：
- 删除 `FREE_WINDOW_DEFAULT` 中的 `until`/`start_hour`/`end_hour` 硬编码（保留常量壳仅作 C5 回退兜底，或整段移除，由 C5 决定）；
- `resolve_source("auto")` 改为：扫描器存在当前免费模型 → 返回 `("all", scanner_reason)`；否则 `("custom", reason)`；
- `is_free_window(model_id, now)` 改为：优先用扫描器结果判定该 id 是否 `free_now`；扫描器不可用时回落既有 `models.json` `freeWindow` 链（见 Decision 5）。

**为什么**：彻底消除「hy3 被错排收费」「活动 10-10 已结束误判」两类静默错误（SC1 / SC4）。

### 4. `next` 输出裸 id（对应 C4）

**方案**：`cmd_next` 输出的 `selected["id"]` 对程序模型保持**裸 id**（已是如此，无需改输出格式）；
SKILL.md 的「委派铁律」收窄为：**仅当所选为 BYOK 兜底路线时**，子代理才对模型名加 `custom-local:` 前缀；
程序侧免费模型一律裸 id 委派。在 `next` 的 JSON 输出中新增 `recommended_prefix` 字段
（`"custom-local:"` 仅对 BYOK 项，`""` 对程序项），供 SKILL.md 派生文档与子代理模板消费。

**为什么**：`custom-local:` 前缀是为应对「同名劫持 + 429 限流」而加，这两坑只对 BYOK 路线存在；
程序模型走裸 id 后，前缀补丁对默认路线不再需要，避免无意义前缀污染（SC3）。

### 5. 缓存降级（对应 C5，新增强化）

**方案**：`scan_program_config` 的降级**两级**：
- 一级（单根异常）：缺文件 / JSON 损坏 / 字段缺失 → 该根跳过并 `warning`，继续用另一根；
- 二级（扫描器整体不可用：双根都缺失 / 双根都异常 / 字段完全无法解析）：
  → **显式告警** + 回退到既有 `models.json` `freeWindow`（含 `FREE_WINDOW_DEFAULT` 兜底）链，
  不静默返回空清单；若回退链本身也失败（如 models.json 缺失）→ `sys.exit(non-zero)` 报错。
- 核心不变量：**任何路径都不得静默产出空候选集并让上层误判为「无免费」**（SC2）。

**为什么**：缓存未生成 / 程序升级改字段名是真实风险；降级必须显式，否则比硬编码更危险（把免费误判收费）。

## Architecture

```
启动 / 每次 next
   │
   ▼
scan_program_config(roots=[~/.workbuddy/cache, ~/.workbuddy-ai/cache], now)
   │ 读 acc-product-config-v3.json（双根，逐根容错）
   │ 解析 models[].credits + modelPromotions[].(schedule, validUntil, discountedCredits)
   │ effective = base × active_promo_factor
   ▼
ScanResult { per-model: {id, base, effective, free_now, window, valid_until, source_root},
             warnings[], degraded[] }
   │
   ├─ 正常 ─▶ build_free_candidate_pool(now)
   │            └─ 默认 = free_now 裸 id 列表
   │            └─ 空时回退 load_declared_models()（BYOK 兜底，标 source）
   │
   └─ 双根全失败 ─▶ 回退 is_free_window()/models.json freeWindow 链 ─▶ 仍失败则 exit(non-zero)
   │
   ▼
cmd_next: resolve_source(auto) 用 scanner 决策 all/custom
          → 候选集 = build_free_candidate_pool()
          → filter_available(白名单/限流)
          → 轮询选模，输出 selected.id（程序=裸id / BYOK=加 custom-local: 前缀）
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 缓存字段改名（程序升级）致解析失败 | C5 两级降级：逐根容错 + 整体回退 models.json；解析异常不静默（warning/exit） |
| 跨午夜时段（23:00–08:00）边界算错 | `daily[{start,end}]` 支持 `start>end` 跨午夜；单元测试覆盖 23:30 / 00:30 / 08:00 边界 |
| 双根同 id 冲突（effective 不一致） | 合并取更低 effective（保守），避免把收费当免费 |
| 折扣 0.5x 中间态被当成「免费」或「收费」 | `free_now` 严格 = `effective == 0`；0.5x 明确属「折扣」非「免费」，候选池区分 free/discount |
| BYOK 兜底被默认启用导致同名劫持回归 | 仅当扫描器产出为空才回退 BYOK；默认路线零 BYOK |
| SKILL.md 硬编码段未同步删除 | SC4 明确要求 `fstdd validate` 可确认无残留硬编码日期/时段常量；变更须同步三处载荷（install.sh / 镜像 / verify） |

## 不变式（Phase 3 须守住）

1. **不静默空清单**：扫描器/候选池在任何降级路径都不得让上层误判「无免费」（C5/SC2）。
2. **零 API key**：扫描只读本地缓存文件，绝不调用接口或携带密钥（约束）。
3. **双根合并**：两根缓存都必须扫描并合并，AI 根免费模型必须进候选（SC6）。
4. **程序模型裸 id**：`next` 与委派默认用裸 id；`custom-local:` 仅 BYOK 兜底（SC3/C4）。
5. **effective 口径唯一**：`free_now = effective == 0`，折扣≠免费，判定全仓唯一来源。

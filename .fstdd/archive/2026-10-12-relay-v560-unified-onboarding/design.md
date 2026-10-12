# Relay Step 0 重设计：统一启用向导 — 技术设计

## Context

**当前系统状态**：relay 的 Step 0 拆成两块独立渲染：
- ① 时段滚轮：SKILL.md `relay-window-wheel` 块（内联 HTML，消费 `window` 命令输出）
- ② 模型白名单：`inventory` + `free set`（消费 `free_allowlist` state）

**已存在的关键基础设施（本设计直接复用，不重造）**：
- `window`（show）输出含 `per_model` = `_per_model_window_view()`（pick_model.py L507）：逐模型 `{since, until, start_hour, end_hour, source, constraint, constraint_note}`。
- `is_free_window(model_id=None, now=None)`（L559）：逐模型免费判定；v5.5.0 优先消费程序缓存扫描器。
- `_window_mode(mid)`（L481）：`global` / `override` / `unconstrained` 三态。
- `_effective_free_window(mid)`（L458）：全局默认叠加该 id 覆写层。
- 三级配置：覆盖文件 > `models.json` freeWindow > `FREE_WINDOW_DEFAULT`（L198）。
- `window set --model <id> --start-hour --end-hour`（L4073）：逐模型覆写写入。
- v5.5.0 扫描器：读两根 `cache/acc-product-config-v3.json`（L675-677），产出 `by_id`/`free_now`/`window`。
- `origins` 命令：源分类 relay / ow-bridge / qoder-free / external。
- state `free_allowlist = {ids, confirmed_at}`（L1790）+ `load_free_allowlist`（L1793）。

**v5.5.0 现实（数据源）**：扫描宿主程序后，**系统模型自带时间段**：
hy3/hy3-b/hy3-c = x0.00 全天免费；hy4-preview/-dev 仅夜间 23:00-8:00；glm-5.2 夜间 0.50x；deepseek-v4 非高峰 0.50x。
（`window.per_model` 显示层仍把 hy3 误标「受时段约束」，不影响判定。）

**约束**：
- `now_utc()` 是唯一时间源（L148），守 TC-TEST-003。
- `state` 保留未知键（TC-MAINT-004/005），新键可安全存活。
- 回归套件 `tests/run-all.py` 逐文件 subprocess（`text=True`），断言须 ASCII。
- 用户设计决策：归属=渠道（系统=平台免费时段 / 自定义=BYOK+桥接）；hy3 独立「始终免费」组；AgentHub 双层；**系统模型时段用宿主规范·只读；自定义模型逐模型选时段；桥接模型也尝试扫描其免费时段**。

## Decisions

### 1. 统一控件 = 单次渲染 4 段；时段分工 = 系统只读 / 自定义可选（含桥接扫描）

**方案**：SKILL.md 用 `relay-onboarding-wizard` 块替换 `relay-window-wheel`；4 段：
① 始终免费组（系统，宿主规范·只读）② 平台时段组（系统，渠道可切，宿主规范·只读）③ 自定义渠道组（BYOK + 桥接，**逐模型选时段**；桥接模型也尝试扫描其免费时段并预填）④ AgentHub 双层。

**为什么**：诉求「时间段 + 模型 + 归属在一个控件里一起选」。**系统模型的时段由宿主程序规范定义**（平台侧权威），只读展示；**桥接模型（Qoder-free / OpenCode 等）也能被扫描出免费时段**，不假设其无规范；纯 BYOK 无扫描源才纯手工选。这既符合 v5.5.0 数据源事实，也让 UI 更完整。

**备选方案及排除原因**：
- 全局单时段段（v2 原型）：与逐模型现实冲突，被用户否决。
- 让系统模型也可编辑时段：与「直接用宿主规范」冲突，且会掩盖平台真实免费窗口。
- 假设桥接模型无免费时段：被用户否决（桥接的也能扫描）。

### 2. 数据源：消费既有 `window` / `inventory` / 扫描器 / `origins`，不重造

**方案**：新增 `onboard`（无参数=**读**）一次性汇总：
- `system_models`：来自 `PLATFORM_MODELS` + `load_declared_models()` 中 `_source=platform` 的条目；其时段 = 扫描器 `by_id[mid]` / `_per_model_window_view()[mid]`（**只读**）
- `custom_models`：BYOK（`_source=custom` 且非桥接）+ 桥接（`origins` 识别 qoder-free / ow-bridge / external）；其时段：**先尝试扫描**（扫描器/桥接配置），扫到则预填，否则 all-day，用户可调
- `agenthub`：来自 state
输出单一 JSON 供向导预填。

**为什么**：扫描器 + 三级配置 + per_model 视图 + origins 均已存在且经测试；重造会引入双份真相（「契约断层」失败模式）。

### 3. `onboard set` 写入：逐自定义模型 `window set --model` + 白名单 + state 一次落盘

**方案**：`onboard set` 接收向导结果，内部：
1. 对**每个自定义/桥接模型**调 `_write_override_window({start_hour,end_hour}, model_id=mid)`（all_day → 写 `{start_hour:0,end_hour:0}` 恒真语义）
2. **不写系统模型时段**（宿主规范为准）
3. 写 `free_allowlist`（勾选集）
4. 写 `state.relay_onboard = {confirmed_at, groups, custom_periods, agenthub_pref}`

**为什么**：复用既有写入路径（已守 SC-FWOVR 非法值不落盘契约）；state 一次落盘减少锁竞争。

**备选方案及排除原因**：
- 向导直接改 models.json：会动含 API Key 的文件，风险高（默认写覆盖文件即可）。

### 4. `onboard-status` 的 due 判定 = 未确认 或 跨自然日 或 数据漂移

**方案**：`due = (confirmed_at 缺失) or (本地自然日 != today) or (last_config_hash != 当前配置 hash)`。
`last_config_hash` = 对 `{groups, custom_periods}` 规范化 JSON 取 sha256 前 16 位。

**为什么**：吸收 daily-free-confirm 的「每日一次」意图，并补「数据漂移」——若扫描器发现新免费模型/窗口变化（含桥接新模型），即便当天也应重新提示。

**备选方案及排除原因**：
- 仅自然日：漏数据漂移。仅数据漂移：跨天不提醒。

### 5. 存量迁移：`free_allowlist` + 自定义模型 window 覆写 → `relay_onboard`

**方案**：`migrate_to_relay_onboard(state)` 防御性派生：`free_allowlist.ids` → `groups`（按扫描器分类），自定义模型的 window 覆写 → `custom_periods`。旧键保留只读。不写盘除非 `onboard set` 显式触发。

**为什么**：C-MIG-1；脏数据降级为 `groups={}` 空但不报错（R-MIG 缓解）。

### 6. AgentHub 双层：偏好与开通完成态分离

**方案**：`state.relay_onboard.agenthub_pref`（toggle 布尔）与 `state.agenthub_onboarded`（由 multihub-node-onboarding 写）分开。立即开通按钮调 multihub skill。

**为什么**：C-AGHUB-1；AI 不能代跑面板授权，偏好与完成态混存会造成状态不一致（R-AGHUB）。

### 7. 旧 `relay-window-wheel` 保留 1 release 作 fallback

**方案**：C1 新增向导块，旧块暂不删；`onboard-status` due=true 优先新向导，渲染失败回退旧 wheel + stderr warning。

**为什么**：R-UI 缓解，双轨过渡降低回归风险。

## Architecture

```
             ┌────────────────────────────────────────────────────────┐
             │  数据源（全部既有，只读消费）                           │
             │  v5.5 扫描器(2 root cache)   window.per_model(L507)     │
             │  PLATFORM_MODELS/declared    origins(源分类 relay/      │
             │                              ow-bridge/qoder-free/ext)  │
             │  state.free_allowlist        state.relay_onboard        │
             └───────────────┬────────────────────────────────────────┘
                             ▼
   agent 冷启动 ──►  onboard-status ──► {due, confirmed_at, last_config_hash, today, drift}
                             │ due=true
                             ▼
      onboard (读) ──► {system_models(宿主时段·只读), custom_models(扫描预填/可调), agenthub}
                             ▼
       agent 渲染 relay-onboarding-wizard（4 段；② 只读宿主时段；③ 逐模型选时段）
                             │ 用户调整 + 确认
                             ▼
                    [relay-onboard] 回传 ──► onboard set
                             ▼
        ┌────────────────────┴────────────────────┐
        ▼                    ▼                     ▼
 _write_override_window  free_allowlist    state.relay_onboard
 仅自定义/桥接 start/end  (勾选集)          {confirmed_at,groups,
 (系统模型不写)                             custom_periods,agenthub_pref}
                             │
                             ▼
                    onboard-status 再算 due=false（当日+同 hash）

  AgentHub「立即开通」按钮 ──► multihub-node-onboarding skill（本机面板交互）
```

**调用链要点**：
- `cmd_onboard`（读）：扫描器分类 + `_per_model_window_view()` + `origins` + state → JSON。
- `cmd_onboard_set`（写）：仅自定义/桥接模型 `_write_override_window` + `free_allowlist` + `state.relay_onboard`。
- `cmd_onboard_status`：读 `state.relay_onboard`，算 due（自然日 + config hash）。
- `next`/`inventory` 增 `onboard_due` 布尔（复用 `_onboard_due()`）。
- 全部日期访问经 `now_utc()`。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| R-UI 新向导 4 段渲染失败 | 保留旧 wheel fallback 1 release + 渲染失败 stderr warning |
| R-MIG 存量脏数据迁移残缺 | `migrate_to_relay_onboard` 防御归一化，脏字段降级为空不报错 |
| R-AGHUB 偏好/开通态不一致 | `agenthub_pref` 与 `agenthub_onboarded` 分离存储 |
| R-DEP 旧 wheel 静态断言假红 | Phase 3 同步更新 test-free-model-confirm.py 文案断言 + TC-UOB-008 |
| R-V55 per_model 显示 bug（hy3 误标） | 向导以扫描器判定为准，不读 window.per_model 的 constraint 文案 |
| R-HASH config hash 不稳定 | hash 前对 `{groups, custom_periods}` 规范化排序，消除 dict 顺序依赖 |
| R-BC onboard set 写 models.json | 默认写覆盖文件，仅 `--write-models-json` 才动含 Key 的 models.json |
| R-SYS 系统模型时段被误写 | `onboard set` 对 `_source=platform` 的模型**跳过** window 写入（宿主规范为准） |
| R-BRIDGE 桥接扫描不可达 | 桥接端点不可达时静默跳过扫描，回落用户手选；不阻断向导 |

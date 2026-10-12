# free-model-relay v5.6.0：Qoder-free 作为 OpenAI 兼容源接入 — 技术设计

## Context

- **relay 现状**：`free-model-relay` v5.5.0（`scripts/pick_model.py`，约 4206 行）是单文件 Python CLI。
  模型来源 = `models.json`（`vendor=Custom` 全部纳入候选池，`_source="custom"`）与平台内置模型合并；
  `auto` 源在免费时段扩到 `all`、收费时段回落 `custom`（`resolve_source` L1690-1704）。
  候选池天然包含**所有** `vendor=Custom` 条目（`load_models` L1596-1599），BYOK 项在 `next` 时一律加
  `custom-local:` 前缀（`cmd_next` L2318）。因此：任何以 `Custom` 条目建档的模型**自动进入默认免费候选池**，
  无需用户显式 allowlist 勾选。
- **多根**：`DATA_ROOT_WHITELIST = [".workbuddy", ".workbuddy-ai"]`（L56），`HOME` 展开（L53）。
  运行时按 `FMR_DATA_ROOT` / `FMR_MODELS_JSON` 覆盖或双根自动探测选一个活跃根（L125-138）。
- **Qoder-free**：本地已装 v0.1.0（`D:/tools/qoder-free`），把 Qoder 账号包装成标准 OpenAI 兼容端点
  `http://127.0.0.1:8210/v1`，`api_key` 自动生成于 `config.json`，面板 `:8210/panel`。它自身已含多账号加权选号、
  会话粘性、限流冷却、连败熔断、单账号并发等治理——对 relay 而言是**单一聚合端点源**。
- **缺口**：relay 当前只认 `models.json` 里带 `*Owner` 标记的 Custom 条目（relay / ow-bridge / external），
  Qoder-free 模型尚未进 `models.json`，relay 无从调度。缺的仅是「探测端点并自动建档」这一步。
- **约束继承**：`*Owner` 判定口径锁定为「键名以 `Owner` 结尾、大小写敏感」（L3449-3474，REQ-MO-008），
  禁止使用子串判据（`buddyBridgeOwner` 历史坑）；`models add` 的 `relayOwner` 对称正例（SC-MO-021）；
  apiKey 一律遮蔽输出（SC-MO-012）；INT-005 守门「policy 快照零密钥泄漏」。

## Decisions

### D1. 发现机制：探测 `/v1/models` 并幂等写入 Custom 条目（C1）

**方案**：新增 `discover_qoder_free()`：
1. 解析 Qoder-free `config.json` 取 `api_key` 与 `listen`（默认 `127.0.0.1:8210`）；
2. `GET {base}/v1/models` 带 `Authorization: Bearer {api_key}`；
3. 把返回的 `data[].id`（保留 `cn:`/`global:` 区域前缀）逐个 upsert 成
   `{id, vendor:"Custom", url:"http://127.0.0.1:8210/v1", apiKey:<QF key>, qoderFreeOwner:"qoder-free"}`。

**为什么**：Qoder-free 自带多账号治理，relay 只消费其端点即可，无需自己再做账户级调度；复用既有候选池 /
配额 / `custom-local:` 转发链路，零改动池逻辑。

**备选方案及排除**：
- 让用户每次手工 `relay models add`：排除——易错、不可复现、不符合「自动发现」诉求（用户 2026-10-12 明确要自动发现）。
- 把 Qoder-free 账号直接塞进 relay 自有调度：排除——与 Qoder-free 自身治理叠加会抖动/误熔断（见 D4）。

**幂等 / 安全细则**：条目已存在且带 `qoderFreeOwner` → 更新 `url`/`apiKey`，不重复创建；
若同 `id` 条目带**其它** owner（`relayOwner` / `buddyBridgeOwner`）→ 跳过，绝不覆盖他人条目（SC-MO-020 同构）。
写入复用 `models add` 的 `_append_model_entry` + `_write_models_json_entries`（原子写 + 备份 + 锁），apiKey 只经
`_mask_secret` 输出。

### D2. 自动触发 + TTL 缓存（C1）

**方案**：发现逻辑接入两处冷路径——
- `cmd_scan`：扫描新增/移除模型前先跑一次带 TTL 的发现；
- `cmd_next` / `cmd_inventory` 入口：检查 STATE_FILE 中 `qoder_free_last_discovery` 时间戳，超过默认 **60s** 才
  触发一次 best-effort 发现（异常全吞，绝不阻断选模型）。
另保留显式子命令 `relay qoder-free sync`（无视 TTL 强制刷新）与 `relay qoder-free status`
（可达性 / 已发现模型数 / 上次探测时刻）。

**为什么**：用户要「自动发现」；但每次 `next`（子代理高频调用）都联网探测会拖慢热路径且易抖动——
TTL 缓存把联网频率压到 ≤1 次/60s，且发现失败一律静默跳过。

**备选**：仅显式 `sync`：排除——不满足自动发现诉求。

### D3. 来源归类：qoder-free 成为独立 tool 标签（C2）

**方案**：
- `KNOWN_EXTERNAL_OWNERS` 增加 `"qoderFreeOwner": "Qoder-free"`（L3463，仅用于可读文案）；
- 引入 `OWNER_TOOL_MAP = {RELAY_OWNER_KEY: "relay", "buddyBridgeOwner": "ow-bridge", "qoderFreeOwner": "qoder-free"}`
  改写 `_detect_source_tool`（L1994-2017），按标记派生 tool 标签；
- `cmd_origins`（L2056）的 `free_semantics` 分支把 `"qoder-free"` 与 ow-bridge/external 同口径 →
  `quota(third-party-managed)`。

**为什么**：SC 要求 origins 把 Qoder-free 归为**独立**源（不是 OW Bridge 的别名）；
`qoderFreeOwner` 以 `Owner` 结尾，天然被 `_owner_marker_keys`（L3466）捕获，与 REQ-MO-008 后缀判定口径完全一致，
不破坏 ow-bridge / relay 既有分类（TC-QF-003 守门）。

### D4. 默认进池 + 单一聚合源治理（C3）

**方案**：Qoder-free 条目为 `vendor=Custom` → 天然进入候选池（与 ow-bridge 同口径），**不要求**用户显式
allowlist 勾选（`load_declared_models` 对 Custom 预勾 `default_free=True`，L1661-1662）。
relay 仅把 Qoder-free 当**单一聚合端点**暴露：其多账号治理完全交给端点；relay **不**对其叠加账户级轮换 /
熔断 / 并发控制，仅在多个 qoder-free `id` 间做既有模型级轮询（属正常候选选择，非账户调度）。

**为什么**：避免与 Qoder-free 自身调度叠加导致抖动 / 误熔断；同时用最小改动拿到「默认免费源」收益。

### D5. 配置路径可配置 + 可测（C1）

**方案**：
- config 路径：Windows 默认 `D:/tools/qoder-free/config.json`，其它 OS 默认 `~/qoder-free/config.json`；
  可被环境变量 `QODER_FREE_CONFIG` 或 relay 配置键 `qoder_free.config_path` 覆盖。
- Base URL：默认 `http://127.0.0.1:8210/v1`，可被 `QODER_FREE_BASE` 覆盖。
- 发现函数**接受可注入的 probe/http 调用**（测试用 `unittest.mock` 替换，避免触网）。

**为什么**：便携 + 可离线单测；与 v5.5.0 既有的 `FMR_*` 环境变量覆盖纪律一致。

### D6. 失败静默（约束：零阻断）

**方案**：config 缺失 / 端点不可达 / 返回非 200 / `data` 为空 → **不写 stdout、不抛异常、不阻断**任何 relay 流程；
仅在 stderr 输出 debug 级信息（默认安静）。正常场景（Qoder-free 未启动）表现为「无操作」。

**为什么**：relay 既有测试（如 `test-relay-source-governance`、`test-scheduler-*`）会捕获并断言输出，
任何 stdout / 非预期 stderr 噪声都可能让既有用例变红；且「未装 Qoder-free」是常态不应报错。

### D7. id 区域前缀（cn:/global:）（约束末条，Phase 3 验证项）

**方案**：建档时 `id` 原样保留区域前缀；`next` 返回 `custom-local:<id>`，经 `models.json` 按 `id` 精确匹配路由到
`127.0.0.1:8210/v1`。若平台拒绝冒号 `id`，则在建档时做**可逆** sanitize 并在 `origins`/`next` 输出还原。
列为 Phase 3 实测验证项（SC9）。

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Qoder-free 本地网关 (D:/tools/qoder-free, 已装 v0.1.0)        │
│   - 多账号治理(加权/粘性/冷却/熔断/并发)  ← 不归 relay 管       │
│   - 暴露 OpenAI 兼容: GET  /v1/models  (Bearer api_key)        │
│                 POST /v1/chat/completions                     │
│   - config.json: {api_key, listen:127.0.0.1:8210}             │
└───────────────▲──────────────────────────────────────────────┘
                │ ① 探测 /v1/models
┌───────────────┴──────────────────────────────────────────────┐
│  relay.discover_qoder_free()  (新增, TTL 60s 缓存)            │
│   cmd_scan / cmd_next / cmd_inventory 冷路径触发 (best-effort) │
│   relay qoder-free sync (强刷) / status (排障)                │
│   写入 models.json Custom 条目 {id, vendor:Custom,            │
│     url:.../v1, apiKey:<QF>, qoderFreeOwner:"qoder-free"}     │
└───────────────▲──────────────────────────────────────────────┘
                │ ② 候选池天然包含 (vendor=Custom ⇒ _source="custom")
┌───────────────┴──────────────────────────────────────────────┐
│  relay 既有调度内核 (不改动)                                  │
│   load_models("custom"/"all") → filter_available → next      │
│   custom 源 ⇒ recommended_prefix="custom-local:"             │
│   origins: _detect_source_tool ⇒ tool="qoder-free"           │
│           free_semantics=quota(third-party-managed)          │
└───────────────▲──────────────────────────────────────────────┘
                │ ③ 子代理 model="custom-local:<id>" → 路由到 127.0.0.1:8210/v1
┌───────────────┴──────────────────────────────────────────────┐
│  AI 子代理 (hy3 等免费额度之外的补充免费源)                    │
└──────────────────────────────────────────────────────────────┘
```

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| Qoder-free 未启动 / config 缺失 / 返回空 → 探测失败 | TTL 缓存保证 `next` 热路径不每次联网；任何失败分支走 warn+跳过，不向上抛（D6）。TC-QF-002/008 守门。 |
| 发现写入与并发 `next` 抢 models.json | 复用 `models add` 的原子写 + 备份 + 锁；发现全程 try/except，失败不落盘（D1）。 |
| apiKey 落 models.json 后，policy/列表输出误带 key 泄漏 | 约束：所有对外输出走 `_mask_secret`/剥离（SC-MO-012 + INT-005）；TC-QF-005 守门。 |
| `qoderFreeOwner` 被子串判据误判为 `relayOwner`（buddyBridgeOwner 历史坑） | 沿用 `_owner_marker_keys` 的 `endswith("Owner")` 精确判定；`_detect_source_tool` 改用 `OWNER_TOOL_MAP` 按标记派 tool（D3）。TC-QF-003 守门。 |
| relay 对 qoder-free 再叠账户级调度，与端点自身治理叠加致抖动/误熔断 | C3：qoder-free 仅作模型级候选，relay 不引入账户级二次调度（D4）。 |
| `cn:`/`global:` 冒号 id 无法被子代理精确匹配 | D7 原样保留 + 可逆 sanitize 兜底；Phase 3 实测（SC9）。 |
| 双根一致性：发现写活跃根，另一根未同步 | 发现只写活跃 `MODELS_JSON`；跨根同步沿用 v5.5.0 双根解析纪律（SC8）；`qoder-free sync` 可逐根重跑。 |
| 既有测试因发现日志变红 | 失败静默、不污染 stdout/stderr（D6）；CI 回归（`tests/run-all.py`）验证零回归。 |

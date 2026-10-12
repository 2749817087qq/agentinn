# free-model-relay v5.6.0：将本地 Qoder-free 网关作为 OpenAI 兼容源接入（自动发现 + 默认进免费池）

<!-- source_hash: 21c21da5644f0049 -->
<!-- generated_at: 2026-10-12T10:47:15+00:00 -->
<!-- canonical: canonical/proposals/2026-10-12-relay-v560-qoder-free-source.yaml -->

## Why

2026-10-12 已在本地开发机安装 Qoder-free v0.1.0（D:/tools/qoder-free），它把 Qoder 账号包装成标准 OpenAI 兼容端点（Base URL http://127.0.0.1:8210/v1，api_key 在 config.json），让被锁在 Qoder 客户端里的 免费/折扣模型能被任意 OpenAI 客户端调用。但 relay 当前只认 models.json 里带 *Owner 标记的 Custom 条目 （relay / ow-bridge / external），Qoder-free 的模型尚未进入 models.json，relay 无从调度——等于把已装好的 本地免费额度闲置，且每次都要手工 models add，易错、不可复现。


## What Changes

- 新增自动发现能力 discover_qoder_free()：读取 Qoder-free 的 config.json（api_key 与可选 listen 地址）， 探测 GET {base}/v1/models（带 Bearer api_key），把返回的模型逐个写成 models.json 的 Custom 条目，字段为 {id, vendor:"Custom", url:"http://127.0.0.1:8210/v1", apiKey:<QF key>, qoderFreeOwner:"qoder-free"}。 id 采用模型原始 id（保留 cn:/global: 区域前缀语义）。幂等：条目已存在则更新 url/key、不重复创建。 端点不可达 / config 缺失 / 返回空 data 时静默跳过（仅 warn，不抛异常、不阻断 relay 其它流程）。 **自动触发**：(a) 接入既有 scan 命令（scan_program_config 之外新增一步）；(b) 在 load_models / next 的 冷路径上做 TTL 缓存自动探测（默认 60s 重探一次，last_discovery 时间戳存于 relay state），避免每次 next 都 联网。另保留显式子命令 relay qoder-free sync（无视 TTL 强制刷新）与 relay qoder-free status（显示可达性 / 已发现模型数 / 上次探测时刻）供手动与排障。

- 在 KNOWN_EXTERNAL_OWNERS 增加 "qoderFreeOwner": "Qoder-free"，使 origins 命令将其归类为 qoder-free 源， free_semantics 与 ow-bridge 同口径（quota(third-party-managed)）。

- 默认进池 + 单一聚合源治理：Qoder-free 条目为 vendor=Custom，天然进入候选池（与 ow-bridge 同口径）， 无需用户显式 opt-in。relay 仅把 Qoder-free 当**单一聚合端点源**暴露——它自身已含多账号加权选号、会话粘性、 限流冷却、连败熔断、单账号并发与单次轮换；relay 不对其叠加账户级二次轮换/熔断（避免双重调度）。模型级选择 （next 在多个 qoder-free 模型 id 间轮询）仍按既有候选池逻辑，属正常模型选择而非账户调度。

- 新增测试：TC-QF-001 探测成功→写 Custom 条目（含 qoderFreeOwner/url/apiKey）；TC-QF-002 端点不可达→跳过不报错； TC-QF-003 origins 把 qoderFreeOwner 归类为 Qoder-free 源；TC-QF-004 模型进入 inventory 且默认 next （--source auto/custom）即可返回它们（无需 allowlist 勾选）；TC-QF-005 policy 快照仍不含 apiKey（零泄漏， 复用 INT-005 守门）；TC-QF-006 TTL 缓存——连续两次 next 之间不重复联网探测（last_discovery 时间戳生效）。


### New Capabilities

- **discover_qoder_free**：探测本地 Qoder-free 网关 /v1/models，将其模型以 Custom 条目（带 qoderFreeOwner 标记）幂等写入 models.json；端点不可达时静默跳过。支持 scan 接入 + TTL 缓存自动触发 + 显式 sync/status 子命令。

### Modified Capabilities

- **origins 来源归类**：KNOWN_EXTERNAL_OWNERS 增加 qoderFreeOwner→Qoder-free，origins 命令将此类条目归类为 Qoder-free 源（third-party-managed 语义）。

## Success Criteria

- [ ] SC1：relay qoder-free sync（或 scan）在 Qoder-free 已启动且已加账号时，能把 /v1/models 返回的模型写成 models.json 的 Custom 条目，且每条含 qoderFreeOwner、url=http://127.0.0.1:8210/v1、apiKey=<QF key>。
- [ ] SC2：Qoder-free 未启动或 config 缺失时，relay qoder-free sync/scan/next 静默跳过（仅 warn），不抛异常、不导致 relay inventory/next 失败或显著变慢。
- [ ] SC3：relay origins 把带 qoderFreeOwner 的条目归类为 Qoder-free 源，free_semantics 为 quota(third-party-managed)。
- [ ] SC4：qoder-free 模型出现在 relay inventory（vendor=Custom），且在默认 relay next（--source auto/custom，无 allowlist 勾选）即可被返回进入候选——即默认进免费候选池。
- [ ] SC5：以 qoder-free 模型启动子代理时，relay next 返回 custom-local:<id>，且请求经 models.json url 路由到 127.0.0.1:8210/v1（端到端打通）。
- [ ] SC6：TC-QF-001~006 全绿（发现写条目 / 不可达跳过 / origins 归类 / 默认进池 / 快照零泄漏 / TTL 缓存不重复联网）。
- [ ] SC7：Qoder-free config.json 路径可被 QODER_FREE_CONFIG / qoder_free.config_path 覆盖，relay 在默认路径与覆盖路径下均可发现。
- [ ] SC8：两根（~/.workbuddy 与 ~/.workbuddy-ai）models.json 同步适配，qoder-free 条目在两根均被正确识别与归类，且与 v5.5.0 双根同步纪律一致。
- [ ] SC9：id 含 cn:/global: 区域前缀时，子代理 model 参数 custom-local:<id> 能精确命中 models.json 条目（若平台拒冒号 id，sanitize+还原方案通过 Phase 2/3 验证）。

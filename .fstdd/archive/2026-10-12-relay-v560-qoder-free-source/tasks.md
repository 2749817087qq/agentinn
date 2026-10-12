# v5.6.0-qoder-free-source 任务清单

## 1. 来源归类内核（P0）— Slice 1

- [x] 1.1 `KNOWN_EXTERNAL_OWNERS` 增 `"qoderFreeOwner": "Qoder-free"`（仅用于可读文案）
- [x] 1.2 新增 `OWNER_TOOL_MAP = {relayOwner:"relay", buddyBridgeOwner:"ow-bridge", qoderFreeOwner:"qoder-free"}`
- [x] 1.3 `_detect_source_tool` 改用 `OWNER_TOOL_MAP` 按标记派 tool 标签（**不改** relay/ow-bridge 既有口径）
- [x] 1.4 `cmd_origins` 的 `free_semantics` 分支把 `"qoder-free"` 与 ow-bridge/external 同口径
      ⇒ `quota(third-party-managed)`
- [x] 1.5 常量：`QODER_FREE_OWNER_KEY` / `QODER_FREE_OWNER_VALUE` / `QODER_FREE_LISTEN_DEFAULT` /
      `QODER_FREE_BASE_DEFAULT` / `QODER_FREE_TTL_SECONDS` / `QODER_FREE_STATE_KEY`

## 2. discover 核心（P0）— Slice 2

- [x] 2.1 `resolve_qoder_free_config_path()`：`QODER_FREE_CONFIG` 环境变量优先，否则按 OS 默认
      （Windows `D:/tools/qoder-free/config.json`；其它 `~/qoder-free/config.json`）
- [x] 2.2 `resolve_qoder_free_base(cfg)`：`QODER_FREE_BASE` 整体覆盖，否则由 `cfg.listen` 推导
      `http://{listen}/v1`（默认 `127.0.0.1:8210`）
- [x] 2.3 `_probe_qoder_free_models(base_url, api_key)`：`GET {base}/v1/models`（Bearer），
      成功返回 JSON，任何失败抛异常（由调用方吞）
- [x] 2.4 `_safe_persist_qoder_free(before, new_data)`：备份 + 原子写 + 校验「非 qoder-free 条目逐字不变
      （含 apiKey）」；失败回滚，返回 `(backup, err)`，**不**调 `_cli_fail`（D6）
- [x] 2.5 `discover_qoder_free(force=False, _probe=None)`：config 解析 → probe → 逐 id upsert
      （新条目 `{id, vendor:"Custom", url, apiKey, qoderFreeOwner}`）
- [x] 2.6 幂等：同 id 已存在且带 `qoderFreeOwner` → 更新 url/apiKey（数组长度不变）；
      同 id 带其它 owner（relay/ow-bridge）→ 跳过不覆盖（SC-MO-020 同构）
- [x] 2.7 失败静默：config 缺失 / 不可读 / 无 api_key / probe 失败 / 空 data / 持久化失败
      一律 `ok=False` 返回，不抛异常、不刷 stdout（SC-003/004）
- [x] 2.8 成功摘要含 `apiKey_masked`（`_mask_secret`）、`written_to`、`backup`、`discovered/updated/skipped`

## 3. TTL 自动触发（P0）— Slice 3

- [x] 3.1 `_touch_qoder_free_discovery()`：成功发现后在 `STATE_FILE` 记 `qoder_free_last_discovery`
      时间戳（`now_utc().isoformat()`，守 TC-TEST-003 单一时间源）
- [x] 3.2 `maybe_discover_qoder_free(force=False, _probe=None)`：TTL（默认 60s）内不重复联网；
      异常全吞（best-effort）
- [x] 3.3 安全闸 `FMR_QF_AUTODISCOVER`：`0/false/off/no` ⇒ 彻底禁用（保护既有测试套件 /
      避免真实 models.json 意外改写）
- [x] 3.4 `cmd_scan` 冷路径挂载 `maybe_discover_qoder_free()`（扫描前先发现，SC-006）
- [x] 3.5 `cmd_next` 冷路径挂载 `maybe_discover_qoder_free()`（选模型前 best-effort 发现）

## 4. 子命令 sync/status（P1）— Slice 4

- [x] 4.1 `cmd_qoder_free(args)`：`sync` → `discover_qoder_free(force=True)` 出 JSON + 退出码；
      `status` → config 路径/存在性/base/可达性/模型数/上次探测时刻
- [x] 4.2 子命令注册：`sub.add_parser("qoder-free")` + 子动作 `sync`/`status` + `handlers["qoder-free"]`

## 5. 默认进免费候选池（P0）— Slice 5

- [x] 5.1 验证 `vendor=Custom` ⇒ `_source="custom"` 天然进候选池（不改池逻辑）
- [x] 5.2 验证 `inventory` 的 `declared` 列出该条目（`default_free=True`），
      `next --source auto` 无需 allowlist 勾选即返回它
- [x] 5.3 验证 `next` 返回 `recommended_prefix == "custom-local:"`（`_source=custom` 路径）

## 6. 零泄漏守门（P0）— Slice 6

- [x] 6.1 验证 `list` / `inventory` / `profile` / `origins` 输出均无 apiKey 明文（INT-005 / SC-MO-012）
- [x] 6.2 apiKey 仅以 `_mask_secret` 遮蔽形态或完全不出现

## 7. 测试与验证（P0/P1）— Slice 7

- [x] 7.1 新建 `D:/tools/多层次agent/tests/test-relay-qoder-free-source.py`（TC-QF-001~009，19 断言）
- [x] 7.2 Slice 1 单元测试（origins 归因）RED→GREEN
- [x] 7.3 Slice 2 单元测试（探测/写入/幂等/不可达/config 覆盖）RED→GREEN
- [x] 7.4 Slice 3 单元测试（TTL 不重复联网）RED→GREEN
- [x] 7.5 Slice 5/6 集成测试（默认进池 / 零泄漏）RED→GREEN
- [x] 7.6 真实 HOME 守卫：用例前后比对 `~/.workbuddy` 下 models.json/state/usage sha256 不变
- [x] 7.7 AI 根 → WB 根同步 + sha256 校验
- [x] 7.8 全量回归 `tests/run-all.py` 通过（除已知环境问题）
- [x] 7.9 14 类失败模式检查 + design-adjustments.md + test-report.md

<!--
优先级说明：
- P0：阻塞性任务，完成前无法进入下一阶段
- P1：重要任务，应在当前阶段完成
- P2：可延后到后续版本的任务
依赖标注：(依赖 #N.M) 表示此任务依赖第 N 组第 M 个任务完成后才能开始
-->

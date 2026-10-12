# Spec: qoder-free-source-integration

> Change: 2026-10-12-relay-v560-qoder-free-source | Auto-generated Human View

## Requirements

### Requirement: discover_qoder_free 探测 Qoder-free /v1/models 并将模型以 Custom 条目（带 qoderFreeOwner）幂等写入 models.json

#### Scenario: SC-001

- **GIVEN** Qoder-free 已启动且已加账号；config.json 含合法 api_key 与 listen；models.json 当前不含该模型 id
- **WHEN** 调用 discover_qoder_free()（或 relay qoder-free sync）
- **THEN** SHALL 在 models.json 写入一条 Custom 条目，字段为 {id, vendor:"Custom", url:"http://127.0.0.1:8210/v1", apiKey:<QF key>, qoderFreeOwner:"qoder-free"}
- **AND** 条目 id SHALL 等于 /v1/models 返回的模型原始 id（保留 cn:/global: 区域前缀）
- **AND** apiKey 写入时 SHALL 仅经 _mask_secret 输出，绝不在 stdout 回显明文

#### Scenario: SC-002

- **GIVEN** models.json 已存在同 id 且带 qoderFreeOwner 的 Custom 条目
- **WHEN** 再次调用 discover_qoder_free()
- **THEN** SHALL 更新该条目的 url/apiKey，不得创建第二条同 id 条目（数组长度不变）
- **AND** 若同 id 条目带非 qoderFreeOwner 的 owner（relayOwner/buddyBridgeOwner），SHALL 跳过不覆盖

#### Scenario: SC-003

- **GIVEN** Qoder-free 进程未启动（127.0.0.1:8210 不可达）
- **WHEN** 在 cmd_next / cmd_scan / relay qoder-free sync 中触发发现
- **THEN** SHALL 静默跳过（不抛异常、非零退出、不污染 stdout），relay 正常返回既有模型
- **AND** SHALL 不向 stdout 输出任何错误；stderr 仅可有 debug 级信息

#### Scenario: SC-004

- **GIVEN** Qoder-free config.json 路径不存在或文件非法
- **WHEN** 触发发现
- **THEN** SHALL 静默跳过（不抛异常、不写 models.json），relay 流程不受影响
- **AND** SHALL 支持 QODER_FREE_CONFIG 环境变量 / qoder_free.config_path 配置键覆盖默认路径

### Requirement: 发现逻辑通过 TTL 缓存自动触发于 scan/next 冷路径，避免每次联网

#### Scenario: SC-005

- **GIVEN** STATE_FILE 中 qoder_free_last_discovery 时间戳距今 < 60s
- **WHEN** 连续两次 cmd_next 调用（间隔 < TTL）
- **THEN** SHALL 仅在首次触发一次网络探测，第二次在 TTL 内 SHALL NOT 再次联网（probe 调用计数 = 1）
- **AND** TTL 过期后（> 60s）的下一次调用 SHALL 重新探测一次

#### Scenario: SC-006

- **GIVEN** Qoder-free 已启动且 TTL 已过期
- **WHEN** 执行 relay scan
- **THEN** SHALL 在扫描新增/移除模型前先执行一次发现，使新发现的 Qoder-free 模型被纳入 known_models

### Requirement: origins 命令将 qoderFreeOwner 条目归类为独立的 qoder-free 源

#### Scenario: SC-007

- **GIVEN** 某 data-root 的 models.json 含带 qoderFreeOwner:"qoder-free" 的 Custom 条目
- **WHEN** 执行 relay origins
- **THEN** SHALL 将该 root 的 tool 归因为 "qoder-free"，tool_detail 为 "Qoder-free"
- **AND** 该源的 free_semantics SHALL 为 "quota(third-party-managed)"
- **AND** SHALL NOT 被误判为 relay / ow-bridge / external

### Requirement: Qoder-free 模型默认进入免费候选池（单聚合源，无 allowlist 勾选要求）

#### Scenario: SC-008

- **GIVEN** models.json 含带 qoderFreeOwner 的 Custom 条目，且用户未做任何 allowlist 勾选
- **WHEN** 执行 relay inventory 与 relay next --source auto（或 custom）
- **THEN** SHALL 在 inventory 的 declared 模型中列出该条目（default_free=True），且 next SHALL 可在不勾选 allowlist 的情况下返回它
- **AND** next 返回的 recommended_prefix SHALL 为 "custom-local:"（_source=custom 路径）

### Requirement: Qoder-free 接入后，对外可分享输出（policy 快照 / list / inventory / profile）零 apiKey 明文泄漏

#### Scenario: SC-009

- **GIVEN** models.json 含带 qoderFreeOwner 且 apiKey 为真实密钥的 Custom 条目
- **WHEN** 执行任何对外输出命令（list / inventory / profile / origins / policy 快照）
- **THEN** SHALL NOT 在任何 stdout 输出中出现 apiKey 明文
- **AND** apiKey SHALL 仅以 _mask_secret 后的遮蔽形态出现（如 ****）或完全不出现

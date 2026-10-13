# Spec: data-file-migration

> Change: 2026-10-13-relay-agentinn-rename | Auto-generated Human View

## Requirements

### Requirement: 数据文件名常量改为新名：新装环境生成 agentinn-*.json（不再生成旧名文件）

#### Scenario: SC-009

- **GIVEN** 空数据根（无任何 state/usage/window 文件）
- **WHEN** 执行任一写 state 的子命令（如 `free set --ids a`）
- **THEN** SHALL 生成 `agentinn-state.json`（及按需 `agentinn-usage.json` / `agentinn-window.json`）
- **AND** SHALL NOT 生成 `free-model-relay-*.json`

### Requirement: 自动迁移：只读旧、写新、不删旧；幂等

#### Scenario: SC-010

- **GIVEN** 数据根仅有旧文件 `free-model-relay-state.json`（含已知内容），无新文件
- **WHEN** 执行任一读取 state 的子命令（如 `status`）
- **THEN** SHALL 生成 `agentinn-state.json`，其内容 SHALL 与旧文件等价
- **AND** 旧文件 `free-model-relay-state.json` SHALL 仍存在（只读保留，可回滚）

#### Scenario: SC-011

- **GIVEN** 数据根无旧文件也无新文件
- **WHEN** 执行 `status`
- **THEN** SHALL 正常返回（不因缺文件报错），退出码 SHALL 为 0

#### Scenario: SC-012

- **GIVEN** 数据根同时存在旧文件与新文件（新文件含不同于旧的内容）
- **WHEN** 执行 `status` 并读回新文件
- **THEN** 新文件内容 SHALL 保持不变（SHALL NOT 被旧文件覆盖）

#### Scenario: SC-013

- **GIVEN** 已完成一次迁移（新文件已生成）
- **WHEN** 再次执行同一命令
- **THEN** 新文件内容 SHALL 不变，且 SHALL NOT 产生额外副本

### Requirement: 所有权标记双值兼容：旧值与新值均识别为 relay 所有

#### Scenario: SC-014

- **GIVEN** models.json 某条目带 `relayOwner: "free-model-relay"`（旧值）
- **WHEN** 执行 `models add`（或所有权判定路径）
- **THEN** 该条目 SHALL 被识别为 relay 所有（source == "relay"）
- **AND** SHALL NOT 被判为 external 而拒绝/跳过

#### Scenario: SC-015

- **GIVEN** models.json 某条目带 `relayOwner: "agentinn"`（新值）
- **WHEN** 执行所有权判定路径
- **THEN** 该条目 SHALL 被识别为 relay 所有
- **AND** 新写入的标记值 SHALL 为 `agentinn`

#### Scenario: SC-016

- **GIVEN** models.json 某条目带 `qoderFreeOwner` / `buddyBridgeOwner`（其它 owner）
- **WHEN** 执行所有权判定路径
- **THEN** 该条目 SHALL 被识别为 external（非 relay）
- **AND** SHALL NOT 因双值兼容而把其它 owner 误判为 relay

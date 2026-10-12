# Spec: unified-onboarding

> Change: 2026-10-12-relay-v561-agenthub-wiring | Auto-generated Human View

## Requirements

### Requirement: onboard-status / onboard 的 agenthub 对象扩展（只增字段，不改既有 pref/onboarded 语义）

#### Scenario: SC-011

- **GIVEN** 任意 state（含或不含 relay_onboard）
- **WHEN** 执行 onboard-status
- **THEN** agenthub 对象 SHALL 含 pref / onboarded / action / prompted_on 四键
- **AND** pref / onboarded 的取值语义 SHALL 与改动前逐字一致（SC-011 原语义不变）
- **AND** action / prompted_on 为新增键，缺省分别为 "none" / null

### Requirement: onboard set（写）保留既有 agenthub_prompted_on，避免重跑向导清空当日防打扰记录

#### Scenario: SC-012

- **GIVEN** state.relay_onboard.agenthub_prompted_on 已为今天；随后执行 onboard set（agenthub_pref=true）
- **WHEN** 读回 state.relay_onboard
- **THEN** agenthub_prompted_on SHALL 仍为今天（未被清空）
- **AND** confirmed_at / last_config_hash SHALL 按本次 set 更新（其余字段正常刷新）

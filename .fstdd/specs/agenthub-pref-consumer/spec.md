# Spec: agenthub-pref-consumer

> Change: 2026-10-12-relay-v561-agenthub-wiring | Auto-generated Human View

## Requirements

### Requirement: onboard-status / onboard（读）暴露派生判据 agenthub.action（纯由 pref × onboarded 推导）

#### Scenario: SC-001

- **GIVEN** state.relay_onboard.agenthub_pref=true 且 state.agenthub_onboarded 缺失/false
- **WHEN** 执行 onboard-status（或 onboard 读）
- **THEN** 输出 agenthub.action SHALL == "prompt_enable"
- **AND** agenthub.pref SHALL == true；agenthub.onboarded SHALL == false

#### Scenario: SC-002

- **GIVEN** state.relay_onboard.agenthub_pref=true 且 state.agenthub_onboarded=true
- **WHEN** 执行 onboard-status
- **THEN** 输出 agenthub.action SHALL == "none"
- **AND** agenthub.onboarded SHALL == true（已开通 ⇒ 不再需要发起）

#### Scenario: SC-003

- **GIVEN** state.relay_onboard.agenthub_pref=false（或 relay_onboard 缺失 ⇒ pref=None）
- **WHEN** 执行 onboard-status
- **THEN** 输出 agenthub.action SHALL == "none"

#### Scenario: SC-004

- **GIVEN** state.relay_onboard.agenthub_pref=false 且 state.agenthub_onboarded=true
- **WHEN** 执行 onboard-status
- **THEN** 输出 agenthub.action SHALL == "none"

### Requirement: 防打扰记录 agenthub.prompted_on（本地自然日）+ 新写入路径 `onboard agenthub-ack`

#### Scenario: SC-005

- **GIVEN** state.relay_onboard 存在（向导已确认）
- **WHEN** 执行 onboard agenthub-ack
- **THEN** state.relay_onboard.agenthub_prompted_on SHALL 被写为当前自然日（now_utc().date().isoformat()）
- **AND** 后续 onboard-status 的 agenthub.prompted_on SHALL 等于该日期
- **AND** relay_onboard 其余字段（confirmed_at/groups/custom_periods/agenthub_pref/last_config_hash）SHALL 保持不变

#### Scenario: SC-006

- **GIVEN** 同一自然日内已执行过一次 onboard agenthub-ack
- **WHEN** 再次执行 onboard agenthub-ack
- **THEN** agenthub_prompted_on SHALL 仍为该自然日（幂等，无副作用）

#### Scenario: SC-007

- **GIVEN** state.relay_onboard 缺失（向导从未确认）
- **WHEN** 执行 onboard agenthub-ack
- **THEN** SHALL 返回 ok=false（reason=no_relay_onboard）且 SHALL NOT 创建/改写 state
- **AND** 进程退出码 SHALL 为 0（前置不满足，非用法错误）

### Requirement: 联动规则文档化：Agent 读到 prompt_enable ⇒ 发起开通；已提示当日/已开通 ⇒ 跳过（grep 可验证）

#### Scenario: SC-008

- **GIVEN** relay_instruction.md 文本
- **WHEN** 检索 action 联动规则
- **THEN** SHALL 含「agenthub.action == prompt_enable ⇒ 发起 AgentHub 开通（multihub-node-onboarding）」规则
- **AND** SHALL 含「onboarded==true 或 prompted_on==今天 ⇒ 跳过」规则
- **AND** SHALL 含「发起后执行 onboard agenthub-ack 记录当日」规则

#### Scenario: SC-009

- **GIVEN** SKILL.md 文本
- **WHEN** 检索 action 联动规则
- **THEN** SHALL 含与 relay_instruction.md 一致的联动规则（prompt_enable / onboarded / ack 三要点）

### Requirement: 新增 state 子键 agenthub_prompted_on 在「重建 state」路径下不被静默丢失（EXP-2026-0001 交叉检查）

#### Scenario: SC-010

- **GIVEN** state.relay_onboard.agenthub_prompted_on 已写为某自然日
- **WHEN** 执行 next --strategy <切换策略>（触发 state 重建）
- **THEN** 重建后的 state.relay_onboard SHALL 保留 agenthub_prompted_on（及其余 relay_onboard 字段）
- **AND** SHALL NOT 因策略切换而丢弃该键（relay_onboard 整体在保留集内）

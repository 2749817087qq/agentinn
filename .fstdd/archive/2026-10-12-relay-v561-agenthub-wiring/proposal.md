# free-model-relay v5.6.1：接线 AgentHub 偏好（agenthub_pref 消费端落地）

<!-- source_hash: d3e09ce595c9c91c -->
<!-- generated_at: 2026-10-12T15:19:21+00:00 -->
<!-- canonical: canonical/proposals/2026-10-12-relay-v561-agenthub-wiring.yaml -->

## Why

统一启用向导（v5.6.0）第 ④ 段的「新对话自动启用 AgentHub 协作中枢」复选框目前是**半成品**： 勾选后只往 state.relay_onboard.agenthub_pref 写一个布尔值，**没有任何消费方**。 实测三条证据：(1) 全库检索 agenthub_pref —— 除 free-model-relay 自身在 onboard / onboard-status 输出里回显外，无其它消费者；(2) skills/multihub-node-onboarding/ 下 0 命中，该 skill 不读此键； (3) relay_instruction.md / SKILL.md 也没有「读到 pref=true 就发起开通」的规则。 ⇒ 用户勾选后**毫无行为**（既不提示、也不发起开通），「新对话自动启用」的承诺**未兑现**， 控件存在但无行为 —— 属静默失效（正是本项目反复踩的「假绿」类问题）。


## What Changes

- onboard-status 输出新增**派生动作字段** agenthub.action（取值 prompt_enable | none）， 由 `pref == true AND onboarded == false` 推导 —— 给 Agent 一个无歧义的判据，不必自行组合两个布尔。 只增字段、不改既有字段语义（向后兼容）。

- 在 relay_instruction.md 与 SKILL.md 固化**联动规则**：Step 0 读到 agenthub.action == "prompt_enable" ⇒ **发起** AgentHub 开通流程（调 multihub-node-onboarding skill，本机面板交互）； agenthub.onboarded == true ⇒ 跳过、不再提示。

- **防打扰**：引入「已提示」记录（如 state.agenthub_prompted_at），避免每次新对话重复发起开通流程。 具体粒度（一次性 / 每自然日一次）由 Phase 2 设计确定；本 change 只要求「不重复发起」这一可验证性质。

- 新增测试 TC-AW-001~00x：action 派生四态（pref×onboarded 组合）、onboarded 后静默、 防重复提示生效、文档规则存在（grep 可验证）。


### New Capabilities

- **agenthub-pref-consumer**：AgentHub 偏好消费端：派生判据（agenthub.action）+ Agent 联动规则 + 防重复提示

### Modified Capabilities

- **unified-onboarding**：onboard-status 输出扩展 agenthub.action 字段（只增不改）

## Success Criteria

- [ ] SC1：onboard-status 输出含 agenthub.action；pref=true 且 onboarded=false ⇒ prompt_enable，其余三态 ⇒ none
- [ ] SC2：用户勾选 agenthub_pref 后，新对话 Step 0 能自动发起 AgentHub 开通（或明确提示），不再「勾了无效果」
- [ ] SC3：onboarded=true ⇒ 不再发起/提示（幂等；连续多次调用输出一致）
- [ ] SC4：SKILL.md 与 relay_instruction.md 均含该联动规则（可 grep 验证）
- [ ] SC5：新增测试全绿 + 全量回归 25/25 rc=0
- [ ] SC6：防重复提示机制生效（同一自然日内不重复发起）

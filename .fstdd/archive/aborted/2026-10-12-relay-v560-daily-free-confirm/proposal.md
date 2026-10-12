# free-model-relay v5.6.0：免费模型确认改为「每天一次」（自然日 + 代码级每日闸）

<!-- source_hash: 3a599e39dae1a2a6 -->
<!-- generated_at: 2026-10-12T12:07:46+00:00 -->
<!-- canonical: canonical/proposals/2026-10-12-relay-v560-daily-free-confirm.yaml -->

## Why

当前免费模型显式确认（SKILL.md「免费模型显式确认（Step 0 第 ②~⑤ 步）」/ relay_instruction.md「0. 确认免费模型」）在**每次触发**都弹窗确认（SKILL.md L262「每次触发都弹窗确认」、relay_instruction.md L23「每次触发都做」），即便白名单（哪些模型算免费）已持久化在 state 的 free_allowlist.confirmed_at。 前序 relay-v560-qoder-free-source 让更多模型默认进池后，每触发确认的摩擦被放大：一个 change 有 3 个委派点 就会弹 3 次。用户希望把确认节奏从「每触发一次」降为「每天一次」。


## What Changes

- 新增「每日闸」判定：以 free_allowlist.confirmed_at 的**本地自然日** 与 今天本地自然日 比较，决定 Step 0 ② 是否仍需弹窗。新增命令 `free confirm-status` 返回 {due: bool, confirmed_at, confirmed_date, today}，供 AI 在 Step 0 ② 前调用；next / inventory 的 JSON 同步附带 free_confirm_due 字段（避免额外一次调用）。同日（本地 自然日）内已确认过 → due=false，跳过 re-prompt；跨自然日 → due=true，重新弹窗确认并由 free set 更新 confirmed_at。旧 state 无 confirmed_at 或 allowlist 未确认 → due=true（等同现状，向后兼容）。

- 更新文档约定：SKILL.md「免费模型显式确认」段的「确认时机」从「每次触发都弹窗确认」改为「每天首次触发弹窗确认， 同日后续触发跳过（每日闸）」；relay_instruction.md §0「确认免费模型」从「每次触发都做」改为「每天首次触发做， 同日后续跳过」。明确：allowlist 内容本身持久化不变，仅 re-prompt 节奏变化。

- 新增测试：TC-DFC-001 free confirm-status 在 confirmed_at=今天 → due=false；TC-DFC-002 confirmed_at=昨天 → due=true；TC-DFC-003 next/inventory 输出含 free_confirm_due 且与 confirm-status 一致；TC-DFC-004 跨会话 （state 持久化）后同一自然日内仍 due=false；TC-DFC-005 文档改写后，SKILL.md「免费模型显式确认」段的确认时机 改为「每天首次触发」并含「自然日」表述、且该段不再要求「每次触发」（时段确认 ① 段维持每触发，不计入）。


### New Capabilities

- **free confirm-status（每日闸判定）**：基于 free_allowlist.confirmed_at 的本地自然日，返回当前是否仍需确认免费模型（due）；next/inventory 同步输出 free_confirm_due，使「每天一次确认」跨会话可靠生效，不依赖 AI 记忆。

### Modified Capabilities

- **免费模型显式确认 工作流**：Step 0 ② 从「每次触发都弹窗确认」改为「每天首次触发确认、同日后续跳过」，由 confirm-status 驱动；allowlist 持久化口径不变。

## Success Criteria

- [ ] SC1：free confirm-status 在 free_allowlist.confirmed_at 为今天（本地自然日）时返回 due=false；为昨天时返回 due=true。
- [ ] SC2：next / inventory 输出含 free_confirm_due 字段，且值与 free confirm-status 一致（TC-DFC-003）。
- [ ] SC3：跨会话（state 持久化）后，同一本地自然日内 free_confirm_due 仍为 false（TC-DFC-004）。
- [ ] SC4：旧 state 无 confirmed_at 或 allowlist 未确认时，confirm-status 与 next 均视 due=true（向后兼容，等同现状）。
- [ ] SC5：SKILL.md「免费模型显式确认」段的确认时机改写为「每天首次触发」并含「自然日」表述、且该段不再要求「每次触发」；relay_instruction.md §0 同理（TC-DFC-005）。时段确认 ① 段维持每触发、不计入。
- [ ] SC6：TC-DFC-001~005 全绿；确认节奏由每触发降为每天一次，白名单语义与 next 选择结果不变。

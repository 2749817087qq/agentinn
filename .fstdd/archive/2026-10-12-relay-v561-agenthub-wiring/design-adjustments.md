# 设计调整记录 — relay-v561-agenthub-wiring（v5.6.1）

> 汇总 BUILD（Phase 3）期间相对 Gate 2 锁定设计的调整。
> 生成于 Phase 3 Part C（C6）。

## 汇总

| # | 类型 | 严重度 | 触发 | 影响范围 | 状态 |
|---|------|--------|------|---------|------|
| DA-1 | 行为收紧 | Minor | C1 代码评审（medium） | `cmd_onboard_agenthub_ack` + 新增 TC-AW-013 | 已实施 |
| DA-2 | 实现细化 | Minor | 编码期（可测性） | `_agenthub_action` 抽为纯函数 | 已实施 |
| DA-3 | 输出一致性 | Minor | C1 代码评审（low） | `cmd_onboard_set` stdout 摘要 | 已实施 |

## DA-1：ack 适用性门控（行为收紧）

- **原始设计**（proposal C3 / spec SC-005）：`onboard agenthub-ack` 只要 `relay_onboard` 存在
  就写 `agenthub_prompted_on = 今天`。
- **实际调整**：增加**适用性门控** —— 仅当 `agenthub.action == "prompt_enable"` 时才写入；
  否则返回 `ok=false`（`reason=not_applicable`）且**不落盘**。
- **原因**（评审发现 medium）：若调用方在 `action=="none"`（偏好未开 / 已开通）时误调 ack，
  会写入当日标记；此后同一自然日内用户改为 `pref=true`，`action` 变 `prompt_enable`，
  但 `prompted_on == 今天` ⇒ **当日正当的开通提示被静默抑制**。属"静默失效"类缺陷，与本次
  change 的初衷（消除静默失效）直接冲突，故必须修。
- **影响**：SC-005 的**正例不受影响**（pref=true ⇒ action=prompt_enable ⇒ 正常写入）；
  新增反例 TC-AW-013 覆盖两种不适用态（pref=false / 已 onboarded）。
- **兼容性**：新命令，无既有调用方；不影响 `pref`/`onboarded`/`onboard set` 语义。

## DA-2：`_agenthub_action` 抽为独立纯函数

- **原始设计**（design D1）：`action` 判定内联在 `_onboard_agenthub_view` 中。
- **实际调整**：抽为模块级纯函数 `_agenthub_action(pref, onboarded)`。
- **原因**：纯函数可单测、可复用，符合 deep module 原则；判定逻辑（严格 `pref is True`）
  集中一处，避免后续多处复制导致口径漂移。
- **影响**：无行为变化。

## DA-3：`onboard set` 摘要回显 carry-over 值

- **原始设计**（design D5）：`onboard set` carry-over `agenthub_prompted_on`，但 stdout 摘要
  `relay_onboard` 只回显 `confirmed_at/last_config_hash/agenthub_pref`。
- **实际调整**：摘要增回显 `agenthub_prompted_on`（carry-over 后的值）。
- **原因**（评审发现 low）：摘要与实际落盘 state 不一致，调用方若以 stdout 判断 SC-012
  会误判"被清空"。
- **影响**：无行为变化（仅输出字段增加）。

## 非设计调整（测试质量改进，随评审一并实施）

C1 测试评审发现若干断言强度不足/覆盖缺口，已补齐（不改变产品行为与规格）：

- TC-AW-009 补 `onboarded` 断言（对齐 SC-009 三要点）。
- TC-AW-011 补"无 relay_onboard 时四键仍存在"断言（消除键缺失假绿）。
- TC-AW-006 补"第二次同日 ack 前后 state 字节一致"断言（证明真幂等）。
- TC-AW-012 补 `confirmed_at`/`last_config_hash` 被刷新断言（对齐 SC-012 的 AND 子句）。
- TC-AW-010 补 `rc==0` 与"其余 relay_onboard 字段保留"断言。
- 测试 helper 补 `env.pop("PYTHONIOENCODING")`（EXP-2026-0006 编码假红）与真实 HOME 哈希守卫。

## 未采纳的评审建议（记录为已知低危）

- carry-over 仅判 `isinstance(..., str)` 不校验日期格式：脏串不构成抑制（Agent 比对不等即重提示），
  保持与 `_onboard_due` 的宽松口径一致，**不修**。
- design.md 行号锚点漂移：design.md 为历史基线产物，**不改**（改函数名锚定留待后续维护）。
- SKILL.md frontmatter `version` 仍为 `5.6.0`：属**预期**，版本号在 Phase 4 DELIVER 统一 bump。

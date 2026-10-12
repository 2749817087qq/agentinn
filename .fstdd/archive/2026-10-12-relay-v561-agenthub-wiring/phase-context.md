# Phase Context — relay-v561-agenthub-wiring

> 本文件记录本 change 在各 Phase 的关键决策与用户关注点，供 Phase 3/4 复用。
> 生成于 Phase 2 结束（Gate 2 通过，2026-10-12T23:37:42+08:00）。

## 变更一句话

把 v5.6.0 向导里「新对话自动启用 AgentHub 协作中枢」复选框（`agenthub_pref`）**接线**到真实行为：
新增派生判据 `agenthub.action` + Agent 联动规则 + 防打扰记录，消除「勾了无效果」的静默失效。

## Phase 1（UNDERSTAND）关键决策

- 用户明确选择「**接线**」而非「撤下控件」。
- 明确**不含** `free-model-relay → agentinn` 改名（另立 Change 2）。
- 复杂度评分 7/17 → 模式 `standard`（Gate 1 用户确认）。

## Phase 2（SPEC）关键决策（设计 D1~D5）

| 决策 | 内容 | 理由 |
|------|------|------|
| D1 | `agenthub.action` 纯由 `(pref, onboarded)` 推导，不掺防打扰 | SC1 四态可穷举、可判 |
| D2 | 防打扰 = **每自然日一次** | 对齐向导 `due` 的自然日节奏 |
| D3 | `agenthub_prompted_on` 落在 `relay_onboard` **内部** | 天然规避 EXP-2026-0001（重建 state 静默丢键） |
| D4 | 新增写入口 `onboard agenthub-ack`（onboard action 枚举 +1） | 不改只读命令契约；避免复用 set 的粒度不符 |
| D5 | `onboard set` 显式 carry-over `agenthub_prompted_on` | 重跑向导不清空当日标记 |

## 用户关注点（Phase 2 提出的两个待拍板点，用户回复「确认」= 采纳默认）

1. **防打扰粒度**：默认采纳「每自然日一次」（非一次性 / 非不设限）。
2. **新增命令 `onboard agenthub-ack`**：默认采纳（记录「今日已提示」的写入口）。

## 经验库交叉检查结果

- **EXP-2026-0001**（context_loss / high）→ 驱动 D3 + SC-010（策略切换保留 prompted_on）。
- **EXP-2026-0002**（contract_gap / medium）→ 驱动 D4（ack 独立写入路径）。

## Phase 3 必守约束（给 BUILD）

- `pref`/`onboarded` 语义**逐字不变**（只增 `action`/`prompted_on`）。
- 判据**纯本地派生**，零网络。
- ack 在 `relay_onboard` 缺失时安全失败（`ok=false`，退出码 0，不写盘）。
- 新键必须落在 `relay_onboard` 内（勿改顶层保留集）。
- 测试：新增 `tests/test-relay-agenthub-wiring.py`（TC-AW-001~012），全量回归 `tests/run-all.py` 须 25/25 rc=0。
- 双根同步：改动须同步 `~/.workbuddy-ai`（开发）与 `~/.workbuddy`（权威）两根。

## 产出物清单

- `design.md` / `test-plan.md` / `proposal.md`
- `canonical/proposals/2026-10-12-relay-v561-agenthub-wiring.yaml`
- `canonical/specs/{code,agent}/agenthub-pref-consumer.yaml`
- `canonical/specs/{code,agent}/unified-onboarding.yaml`
- `specs/agenthub-pref-consumer/spec.md`（Human View）
- `specs/unified-onboarding/spec.md`（Human View）

## Phase 3（BUILD）切片记录

| 切片 | 内容 | TC 覆盖 | 新增测试 | 状态 |
|------|------|---------|---------|------|
| S1 | `_agenthub_action()` + `_onboard_agenthub_view()` 增 `action`/`prompted_on` | TC-AW-001~004,011（5/5） | 5 | ✅ done |
| S2 | `cmd_onboard_agenthub_ack()` + `_dispatch_onboard` 分支 + CLI 枚举 | TC-AW-005~007（3/3） | 3 | ✅ done |
| S3 | `cmd_onboard_set` carry-over + 策略切换保留 | TC-AW-010,012（2/2） | 2 | ✅ done |
| S4 | `relay_instruction.md` + `SKILL.md` 联动规则（双根） | TC-AW-008~009（2/2） | 2 | ✅ done |

- 新测试文件：`tests/test-relay-agenthub-wiring.py`（12 TCs，全绿）。
- 全量回归：`tests/run-all.py` **26/26 脚本 rc=0**。
- 命中的坑（已修复）：改 `pick_model.py` / `SKILL.md` 后**必须**跑
  `deliverables/free-model-relay/_sync_install_payload.py`，否则 install.sh 内嵌载荷分叉
  → 8 个既有测试（payload-sync-gate / free-window-wheel / fmr-doc-sample / free-model-confirm /
  unified-onboarding / doctor-command / scheduler-×2）连锁失败。
- 触发经验：EXP-2026-0001（S1/S3 设计预防）、EXP-2026-0002（S2 独立写入路径）。


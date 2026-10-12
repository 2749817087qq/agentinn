# free-model-relay v5.6.1 切片执行计划

> Change: `2026-10-12-relay-v561-agenthub-wiring` ｜ 模式：standard ｜ 生成于 Phase 3 Part A

## Dependency Graph Summary

```
[零依赖]
  agenthub-pref-consumer ──┐
  unified-onboarding ──────┴──► (无跨 capability 边)
        │
        ├─ S1 action 派生判据（四态）           ← 基础，其余切片依赖其输出契约
        ├─ S2 ack 写入口 + prompted_on 落盘     ← 依赖 S1（复用 _onboard_agenthub_view 的键）
        ├─ S3 onboard set carry-over + 策略切换保留 ← 依赖 S2（prompted_on 已存在）
        └─ S4 文档联动规则（relay_instruction + SKILL） ← 依赖 S2（规则提及 ack 命令）
```

**并行化说明**：
- 两个 capability 在依赖图中均为零依赖、无环（`cycles: []`）。
- 但 S1~S3 均改**同一文件** `scripts/pick_model.py`，串行编辑以避免冲突 ⇒ 实际串行。
- S4 仅改文档，理论上可与 S1 并行；因规则文本引用 S2 的 `onboard agenthub-ack`，
  语义上排在 S2 之后 ⇒ 整体串行执行（不启用并行组）。

## Slice Execution Plan

| # | 优先级 | 风险 | 预估工时 | 并行组 | TC 覆盖 | 实现目标 | 依赖 |
|---|--------|------|---------|--------|---------|---------|------|
| S1 | P0 | 🟡 高 | M | — | TC-AW-001,002,003,004,011 | `_onboard_agenthub_view()` 增 `action`/`prompted_on` | 无 |
| S2 | P0 | 🟡 高 | M | — | TC-AW-005,006,007 | 新增 `cmd_onboard_agenthub_ack()` + `_dispatch_onboard` 分支 + `onboard` action 枚举 | S1 |
| S3 | P0 | 🟢 中 | S | — | TC-AW-010,012 | `cmd_onboard_set()` carry-over `agenthub_prompted_on` | S2 |
| S4 | P1 | 🟢 中 | S | — | TC-AW-008,009 | `relay_instruction.md` + `SKILL.md` 联动规则（双根） | S2 |

## Rationale

### Slice S1: action 派生判据（P0，先行）
- **依赖关系**：无。是其余切片的契约基础（`agenthub` 对象键集合）。
- **风险分析**：命中 **EXP-2026-0001**（context_loss / high，+2）；Scenario 数 >5（10 个，+1）；
  跨模块交互（CLI 输出 + state 读，+1）⇒ 风险分 4 ⇒ 🟡 高。缓解：严格 `pref is True`，
  只增键不改 `pref`/`onboarded` 语义；TC-AW-011 做逐字回归。
- **工作量估算**：M — 5 个 TC，单文件（`pick_model.py`）。

### Slice S2: ack 写入口 + prompted_on 落盘（P0）
- **依赖关系**：依赖 S1（ack 写的是 S1 暴露的同一子键）。
- **风险分析**：命中 **EXP-2026-0002**（contract_gap / medium）；新增 CLI 分支（+1）；
  涉及 state 读-改-写（+1）⇒ 🟡 高。缓解：独立写入路径、不退出、前置校验缺失即安全失败（SC-007）。
- **工作量估算**：M — 3 个 TC，单文件 + CLI 注册。

### Slice S3: onboard set carry-over + 策略切换保留（P0）
- **依赖关系**：依赖 S2（需先有 prompted_on 才能验证保留）。
- **风险分析**：改动既有 `cmd_onboard_set` 重建逻辑（+1）；策略切换保留属 EXP-2026-0001 验证点（+1）⇒ 🟢 中。
- **工作量估算**：S — 2 个 TC，单文件。

### Slice S4: 文档联动规则（P1）
- **依赖关系**：依赖 S2（规则文本提及 `onboard agenthub-ack`）。
- **风险分析**：纯文档，无运行时风险；但需**双根同步**（`~/.workbuddy-ai` + `~/.workbuddy`）⇒ 🟢 中。
- **工作量估算**：S — 2 个 TC（grep 断言），2 个文件 × 2 根。

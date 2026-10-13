# Phase Context — relay-agentinn-rename

> 本文件记录本 change 在各 Phase 的关键决策与用户关注点，供 Phase 3/4 复用。
> 生成于 Phase 2 结束（待 Gate 2 确认）。

## 变更一句话

把技能 `free-model-relay` 全量改名为 `agentinn`（6 层：源码/文档、目录、文件名、命令入口、数据文件、所有权标记），
提供真实可执行命令 `agentinn <cmd>`，并对旧数据文件与旧 owner 标记做**自动迁移 + 双值兼容**。

## Phase 1（UNDERSTAND）关键决策

- 用户**已拍板**两处（Gate 1 前）：
  1. 「启动命令」形态 = **真实可执行命令 + skill 改名**（非仅改名、非保留旧名别名）。
  2. 旧数据/旧标记 = **自动迁移 + 双标记兼容**（非硬切换）。
- 复杂度评分 **15/17 → thorough**（文件3+行数3+Capability2+风险4+数据2+安全1）。
- 明确**不含** Change 1（已交付）。

## Phase 2（SPEC）关键决策（设计 D1~D7）

| 决策 | 内容 | 理由 |
|------|------|------|
| D1 | 替换用「单次扫描 + 左边界 `(?<![A-Za-z])`」引擎 | 防逐条 replace 的自匹配/顺序坑（rename-refactor） |
| D2 | `agentinn` 入口 = 零交互转发 shim（`bin/agentinn` + `.cmd`） | 单点真理，不复制业务逻辑 |
| D3 | 数据迁移 = 惰性「只读旧 → 写新 → 不删旧」 | 老用户无感 + 可回滚 + 幂等 |
| D4 | owner 标记 = 集合判定 `{agentinn, free-model-relay}` | 老条目不失主（EXP-0002 同构） |
| D5 | 目录改名放 Phase 4 最后 | FSTDD 项目根即 skill 目录 |
| D6 | 排除区显式声明（历史快照保留旧名） | 防误伤（约 1/3 评审发现是误报） |
| D7 | 守卫测试（双向 + 文件名维度 + 幂等 + 排除区 + 反验证） | 「改完不等于能用」 |

## 用户关注点（Gate 1 前已拍板，Gate 2 无需再问）

1. **启动命令形态**：真实可执行命令 `agentinn`（PATH 可用）。
2. **兼容策略**：自动迁移（旧留只读）+ 双标记兼容。

## 经验库交叉检查结果

- **EXP-2026-0001**（context_loss/high）→ 数据路径唯一源 `compute_data_paths`，改常量即全局生效。
- **EXP-2026-0002**（contract_gap/medium）→ 迁移函数不复用会 `_cli_fail` 的写函数，改用 `_atomic_write_json` 静默。
- **EXP-2026-0003**（contract_gap/medium）→ 改 `SKILL.md`/`pick_model.py` 后必须重跑载荷同步（S2 显式纳入）。

## Phase 3 必守约束（给 BUILD）

- 替换引擎**幂等**，须自测。
- 排除区**不参与替换与断言**，逐条给理由。
- 数据迁移**只读旧写新不删旧**；owner **双值兼容**。
- 除命名/路径/标记兼容外，**业务行为逐字不变**。
- 改 `SKILL.md`/`pick_model.py` 后**必须** `_sync_install_payload.py` + `verify_payload.py`。
- 目录改名**留到 Phase 4 最后**。
- 测试：新增 `tests/test-relay-agentinn-rename.py`（TC-ARN-001~008 + TC-DFM-001~008），全量回归 `tests/run-all.py` rc=0。

## 产出物清单

- `design.md` / `test-plan.md` / `proposal.md`
- `canonical/proposals/2026-10-13-relay-agentinn-rename.yaml`
- `canonical/specs/{code,agent}/agentinn-rename.yaml`
- `canonical/specs/{code,agent}/data-file-migration.yaml`
- `specs/agentinn-rename/spec.md`、`specs/data-file-migration/spec.md`（Human View，Gate 2 自动生成）

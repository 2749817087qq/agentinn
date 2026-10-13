# 切片执行计划 — relay-agentinn-rename

> Change: `2026-10-13-relay-agentinn-rename`｜模式 thorough｜长程 full_auto
> 基线：`23f8b7d`

## Dependency Graph Summary

- **Nodes**: 2（`agentinn-rename`、`data-file-migration`）
- **Edges**: 0（两者零依赖）
- **Cycles**: 无
- **zero_dependency**: `agentinn-rename`、`data-file-migration`

## 五步切片分析

### A2a 依赖图分析
两 capability 无依赖边；`data-file-migration` 改动集中在 `pick_model.py` 的数据路径/标记判定，
`agentinn-rename` 改动横跨文档/入口/目录/分发物。可分片独立推进；仅最后的「目录改名」需前置内容改名完成。

### A2b 风险评分

| Capability | 经验库 | 复杂度 | 变更类型 | 合计 | 等级 |
|---|---|---|---|---|---|
| `agentinn-rename` | 0（无 high 匹配） | Scenario 8>5 → +1；跨模块 → +1 | MODIFIED 接口 → +1 | 3 | 🟢 中 |
| `data-file-migration` | EXP-2026-0001 high → +2 | Scenario 8>5 → +1；跨模块 → +1 | NEW | 4 | 🟡 高 |

### A2c 工作量预估
| 切片 | 粒度 | 依据 |
|---|---|---|
| S1 | M | 4 TC，3 文件内容改名 + 替换引擎 |
| S2 | S | 2 TC，2 新文件（`bin/agentinn`、`.cmd`） |
| S3 | L | 8 TC，`pick_model.py` 数据路径 + 迁移 + 标记 |
| S4 | M | 2 TC，目录改名 + 分发物同步 + 载荷复验 |

### A2d 智能分组
1. `agentinn-rename` 拆为 3 片（标识层 / 入口层 / 分发与目录层）—— 因验证时机不同（内容断言 / 入口冒烟 / 目录断言）。
2. `data-file-migration` 独立成 1 片（高风险，8 TC）。
3. 跨 capability 无共享 Scenario，无集成切片。

### A2e 并行化建议
- parallel_group 1 = {S1, S2, S3}（互不依赖）
- parallel_group 2 = {S4}（依赖 S1/S2/S3 全部完成）

## 切片清单

### S1 标识层（agentinn-rename）
- **实现目标**：新增替换引擎 `tools/rename_free_model_relay.py`（单次扫描 + 左边界 + 幂等自测），
  对 `SKILL.md` / `relay_instruction.md` / `scripts/pick_model.py` 执行内容改名。
- **TC 覆盖**：TC-ARN-001（内容无旧名）、TC-ARN-002（frontmatter + 示例）、TC-ARN-004（幂等）、TC-ARN-008（排除区保留）
- **新增测试**：4（`tests/test-relay-agentinn-rename.py` 首批）
- **依赖**：无
- **风险**：🟢

### S2 入口层（agentinn-rename）
- **实现目标**：新增 `bin/agentinn`（POSIX sh）+ `bin/agentinn.cmd`（Windows），零交互转发到
  `scripts/pick_model.py`；文档示例改为 `agentinn <cmd>`。
- **TC 覆盖**：TC-ARN-005（转发等价）、TC-ARN-006（零交互）
- **新增测试**：2
- **依赖**：无（可与 S1 并行）
- **风险**：🟢

### S3 数据层（data-file-migration）
- **实现目标**：`_STATE_NAME`/`_USAGE_NAME`/`_OVERRIDE_WIN_NAME` → `agentinn-*.json`；
  新增 `_migrate_legacy_data_files()`（只读旧写新不删旧、幂等、失败静默）；
  `RELAY_OWNER_VALUE="agentinn"` + `RELAY_OWNER_VALUES={"agentinn","free-model-relay"}` 集合判定。
- **TC 覆盖**：TC-DFM-001~008（8 个）
- **新增测试**：8（`tests/test-relay-agentinn-data-migration.py`）
- **依赖**：无（可与 S1/S2 并行）
- **风险**：🟡（EXP-2026-0001 high）

### S4 分发与目录层（agentinn-rename）
- **实现目标**：`install.sh` 安装路径改 `$HOME/.workbuddy/skills/agentinn` + 生成 `agentinn` 入口；
  `agenthub-install.sh`/`build_agenthub.py`/`README.md`/`INTEGRATION.md`/`ROADMAP.md`/`pick.py`/
  `verify_payload.py`/`_sync_install_payload.py` 同步改名；
  **两根 skill 目录改名** `free-model-relay/` → `agentinn/`；载荷重同步 + 双根字节一致复验。
- **TC 覆盖**：TC-ARN-003（文件名维度）、TC-ARN-007（目录改名）
- **新增测试**：2（追加到 `tests/test-relay-agentinn-rename.py`）
- **依赖**：S1、S2、S3 全部完成
- **风险**：🟡（EXP-2026-0003 载荷分叉必踩区）

## 执行顺序

```
S1 标识层 ─┐
S2 入口层 ─┼─▶ S4 分发与目录层 ─▶ Part C 质量验证
S3 数据层 ─┘
```

（本机单代理串行执行：S1 → S2 → S3 → S4）

## Rationale

- **为何拆 S1/S2/S4**：三者的断言在**不同时点**才为真（内容改名后 / 入口就绪后 / 目录改名后）。
  若合并为一片，前期断言会红，无法满足「每片测试全绿」。
- **为何 S3 独立**：高风险（EXP-0001），且 TC 最多（8），独立成片便于定位失败。
- **为何 S4 必须最后**：目录改名会移动 FSTDD 项目根与 git 仓；且 `verify_payload.py` 改名后
  指向 `agentinn/`，须待目录真正改名后才可能通过。

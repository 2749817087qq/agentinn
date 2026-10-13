# Spec: agentinn-rename

> Change: 2026-10-13-relay-agentinn-rename | Auto-generated Human View

## Requirements

### Requirement: 仓库内标识改名：排除区外的 SKILL.md / relay_instruction.md / scripts/pick_model.py 不含旧名且含新名

#### Scenario: SC-001

- **GIVEN** 改名后的 skill 仓库（排除区外）
- **WHEN** 在 SKILL.md / relay_instruction.md / scripts/pick_model.py 中检索旧名字面
- **THEN** SHALL 0 命中（排除区见 SC-008）
- **AND** 检索新名 `agentinn` SHALL 至少各命中 1 次（证明是改名而非删除）

#### Scenario: SC-002

- **GIVEN** 改名后的 SKILL.md
- **WHEN** 读取 frontmatter
- **THEN** `name` SHALL == "agentinn"
- **AND** SKILL.md 正文标题与用法示例 SHALL 使用 `agentinn <cmd>` 形式

### Requirement: 文件名维度改名：排除区外的文件/目录名不含旧名

#### Scenario: SC-003

- **GIVEN** 改名后的仓库与安装目录
- **WHEN** 递归枚举排除区外的所有文件/目录名并检索旧名
- **THEN** SHALL 0 命中（含数据文件名与 skill 目录名）
- **AND** `*.bak-*` 历史备份目录 SHALL 被排除（保留旧名）

### Requirement: 替换引擎幂等：对已改名文本重复执行结果不变

#### Scenario: SC-004

- **GIVEN** 替换引擎与已改名的文本
- **WHEN** 对已改名文本再次执行替换引擎
- **THEN** 输出 SHALL 与输入逐字一致（幂等）
- **AND** 对含旧名的文本执行一次 SHALL 得到新名，且左边界不误伤 `agentinn-*` 复合词

### Requirement: 真实可执行入口 agentinn：纯转发、零交互、与直调等价

#### Scenario: SC-005

- **GIVEN** 已安装的 `agentinn` 入口（PATH 可用）
- **WHEN** 执行 `agentinn <subcommand> [args]`
- **THEN** 输出 SHALL 与 `python <skill>/scripts/pick_model.py <subcommand> [args]` 逐字一致
- **AND** 退出码 SHALL 与直调一致

#### Scenario: SC-006

- **GIVEN** 非交互上下文（stdin 为管道，无 TTY）
- **WHEN** 执行 `agentinn status`
- **THEN** SHALL 正常返回（不阻塞、不读 stdin）
- **AND** 入口脚本 SHALL NOT 复制任何业务逻辑（仅定位并转发）

### Requirement: 目录改名：两根 skill 目录均为 agentinn/

#### Scenario: SC-007

- **GIVEN** 改名完成后的两个 WorkBuddy 根
- **WHEN** 列出 `skills/` 目录
- **THEN** SHALL 存在 `agentinn/` 且 SHALL NOT 存在 `free-model-relay/`
- **AND** `agentinn/scripts/pick_model.py` SHALL 存在且可执行

### Requirement: 历史快照保留旧名（不误伤）

#### Scenario: SC-008

- **GIVEN** 排除区（`.fstdd/archive/**`、`deliverables/archive/**`、`deliverables/gstack/**`、`RELEASE-AUDIT.md`、历史 memory 日志）
- **WHEN** 检索这些文件内容
- **THEN** SHALL 仍含旧名 `free-model-relay`（未被改写）
- **AND** 排除清单 SHALL 逐条附带理由（写入测试脚本注释）

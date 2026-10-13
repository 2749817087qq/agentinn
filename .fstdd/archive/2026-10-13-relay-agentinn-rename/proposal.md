# free-model-relay → agentinn：全量改名 + 真实可执行入口 + 数据迁移

<!-- source_hash: 5a26ed3a0ab15357 -->
<!-- generated_at: 2026-10-12T23:57:22+00:00 -->
<!-- canonical: canonical/proposals/2026-10-13-relay-agentinn-rename.yaml -->

## Why

技能现名 `free-model-relay` 语义过窄且与实际能力不符：它早已不只是「免费模型」，
而是「多模型接棒器 / 模型旅店」（自定义免费 + 平台内置 + 桥接源，统一调度、时段感知、策略分配）。
同时**没有真实可执行入口** —— 用户/AI 只能写全路径
`python ~/.workbuddy/skills/free-model-relay/scripts/pick_model.py <cmd>`，
既冗长又绑死目录名，改名成本高、可读性差。
用户 2026-10-12 明确要求：改名为 `agentinn`，且**启动命令就是 `agentinn`**。


## What Changes

- **标识层改名（仓库内）**：SKILL.md（frontmatter `name`、标题、正文 15 处）、
relay_instruction.md（10 处）、scripts/pick_model.py（7 处）中所有 `free-model-relay`
字面统一改为 `agentinn`。使用「单次扫描 + 左边界」替换引擎，须幂等。

- **目录层改名（仓库外）**：skill 目录 `free-model-relay/` → `agentinn/`
（`~/.workbuddy/skills/` 与 `~/.workbuddy-ai/skills/` 两根）；`.fstdd` 项目与 git 仓随目录迁移。

- **真实可执行入口 `agentinn`**：新增零交互转发脚本（skill 内 `bin/agentinn` 为源，
安装器安装到 `~/.workbuddy/bin/agentinn` 并给 PATH 指引）。行为 = 原样转发到
`scripts/pick_model.py`（不复制任何业务逻辑）。文档/示例统一改为 `agentinn <cmd>`。

- **数据文件名改名 + 自动迁移**：`free-model-relay-{state,usage,window}.json` →
`agentinn-{state,usage,window}.json`。首次运行**只读旧、写新、不删旧**（可回滚），迁移幂等。

- **所有权标记双值兼容**：`RELAY_OWNER_VALUE` 新值 `agentinn`；所有权判定同时认
旧值 `free-model-relay` 与新值 `agentinn`（避免老条目被误判为 external）。

- **分发物同步**：install.sh / agenthub-install.sh / build_agenthub.py / README.md /
INTEGRATION.md / ROADMAP.md / pick.py / verify_payload.py / _sync_install_payload.py
同步改名（含安装路径 `$HOME/.workbuddy/skills/agentinn`）。

- **测试**：新增改名守卫测试（双向断言：新名存在 ∧ 旧名不存在；覆盖内容 + 文件名两维度；
断言幂等；排除区显式声明并逐条给理由）；补数据迁移 + 双标记兼容测试；全量回归。


### New Capabilities

- **agentinn-rename**：标识/目录/命令入口改名：单次扫描替换引擎 + 真可执行入口 agentinn + 改名守卫断言
- **data-file-migration**：数据文件改名与自动迁移（只读旧写新）+ 所有权标记双值兼容

## Success Criteria

- [ ] SC1：排除区之外，全库（内容 + 文件名）无 `free-model-relay` 残留（双向断言：新名存在 ∧ 旧名不存在）
- [ ] SC2：两根 skill 目录均为 `agentinn/`；`agentinn` 可执行入口存在且 PATH 可用
- [ ] SC3：`agentinn <subcommand>` 输出与 `python <skill>/scripts/pick_model.py <subcommand>` 逐字一致
- [ ] SC4：旧数据文件自动迁移为 `agentinn-*`（旧文件保留只读）；迁移幂等
- [ ] SC5：`relayOwner` 旧值 `free-model-relay` 与新值 `agentinn` 均被识别为 relay 所有
- [ ] SC6：替换引擎幂等（重复执行结果不变）
- [ ] SC7：新增改名守卫测试全绿 + 全量回归 rc=0
- [ ] SC8：历史快照（归档/审计/旧日志）保持旧名不动

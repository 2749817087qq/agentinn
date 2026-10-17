# AgentInn — 多模型接棒器（免费模型中继）

> **版本**：v5.7.1 ｜ **触发**：`免费模型`、`free model relay`、`子代理接棒`、`模型接棒` 等（见文末触发词清单）
>
> 读取 `~/.workbuddy/models.json` 中的自定义免费模型，在 FSTDD 四阶段流程的子代理委派点用这些模型启动 Agent，实现「每个会话通过子代理接棒使用免费 AI」的目标。

---

## 核心理念

WorkBuddy 的 Agent 工具 `model` 参数接受模型 ID。`models.json` 中的自定义模型（`vendor: "Custom"`）可直接作为子代理的运行模型。本 skill 让 FSTDD 流程中的子代理委派点自动选用这些免费模型，实现成本节约。

与 FSTDD 的 **P1 提案审查 / P2 经验交叉检查 / P3 C1 三路并行评审** 三个委派点深度集成。

## 核心能力

0. **时段确认** — 每次触发先渲染「时段滚轮确认窗口」（当前时段 / 免费判定 / 倒计时 / 改起止小时），排在模型白名单勾选之前；回传走 `[relay-window]` 前缀。
1. **显式确认** — 每次触发枚举**全部**可声明模型（含非 Custom vendor + 平台内置），弹窗让用户勾选「哪些是免费模型」，结果存为白名单，relay 只从白名单内挑。
2. **自动检测** — `models.json` 新增模型时自动发现，根据能力字段推断工作类型。
3. **智能分配** — 按任务性质（`code-review` / `spec-writing` / `test-gen` / `doc-review` / `general`）自动匹配最优模型，同分模型间轮询。
4. **流量统计** — 每个模型记录请求数 / 估算 token / 最后使用时间，可设配额。
5. **自动切换** — 模型免费量到（超限 / 限流）时自动跳过，选下一个可用模型。
6. **双轨模型源** — `models.json` 自定义模型 + WorkBuddy 平台内置模型（`hy4-preview` / `hy3`）。
7. **时段感知** — 平台模型免费时段（由程序缓存扫描器动态判定）自动纳入，收费时段自动切回自定义模型。
8. **多策略** — `round-robin` / `fallback` / `capability-match` / `auto` 四种调度策略。
9. **额度告警** — 白名单内模型免费额度用尽时弹窗通知（`record` / `next` 输出 `quota_alerts`）。

## 安装

将整个 `agentinn/` 目录复制到 WorkBuddy 的 skills 目录之一：

- `~/.workbuddy/skills/agentinn`（WorkBuddy 根）
- `~/.workbuddy-ai/skills/agentinn`（WorkBuddy AI 根）

`bin/agentinn`（POSIX / Git Bash）与 `bin/agentinn.cmd`（Windows）是启动器；若 `~/.workbuddy/bin` 已在 PATH，把这两个文件放进该目录即可在终端直接使用 `agentinn` 命令；否则直接用 `python scripts/pick_model.py <子命令>` 亦可。

## 命令速查（`agentinn <子命令>`）

| 子命令 | 作用 |
|---|---|
| `inventory` | 枚举全部可声明模型，供显式确认白名单 |
| `free set` | 写入 / 覆盖免费模型白名单 |
| `window set [--model <id>]` | 设置 / 覆写免费时段（默认写 `~/.workbuddy/agentinn-window.json`） |
| `models add` / `models list` | 录入 / 列出模型条目（`add` 支持交互式、 `--from-env`、 `--stdin`，密钥不回显） |
| `doctor` | 健康检查（结构档 / `--check-endpoint` / `--check-key` / `--check-tools`） |
| `onboard` / `onboard set` / `onboard-status` | 统一启用向导（时段 / 模型 / 归属 / 免费窗口单次渲染） |
| `next` / `record` | 调度选模型 / 记录用量与额度告警 |
| `origins` | 列出模型来源（relay / 桥接 / 平台） |
| `relay-window` | 时段确认窗口回传处理 |
| `qoder-free sync` / `qoder-free status` | 刷新 / 探活 **qoderclicn 桥**（OpenAI 兼容端点 `http://127.0.0.1:8210/v1`，实现为 `D:/tools/qoder-free`：每账号 Node worker + 内存 hook 运行中的 qoderclicn）。子命令名沿用历史；网关未启动时 `reachable:false` 属预期 |

## 触发词

`免费模型`、`free model relay`、`子代理接棒`、`模型接棒`、`免费AI`、`custom model agent`、`free model subagent`、`模型轮换`、`relay agent`、`自动检测模型`、`智能分配模型`、`流量统计`、`模型配额`、`自动切换`、`免费量到了`、`hy3`、`hy4`、`平台模型`、`免费时段`、`确认免费模型`、`免费模型白名单`、`额度用完`、`额度告警`、`时段滚轮`、`免费时段确认`、`改免费时段`、`window set`、`relay-window`

## 目录结构

```
agentinn/
├── SKILL.md              # skill 定义（name / 触发词 / 说明）
├── relay_instruction.md  # 子代理委派指令
├── bin/                  # 启动器：agentinn / agentinn.cmd
├── scripts/
│   └── pick_model.py     # 核心实现（模型选择 / 调度 / 统计）
├── tools/
│   └── rename_to_agentinn.py
├── .gitattributes        # * text=auto eol=lf（保护内嵌载荷字节一致性）
└── .gitignore
```

## 许可

版权归属项目维护方；详见 `SKILL.md`（`license: unknown`）。

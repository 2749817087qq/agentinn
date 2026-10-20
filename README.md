# AgentInn — 多模型接棒器（免费模型中继）

> **版本**：v5.7.7 ｜ **仓库**：<https://github.com/2749817087qq/agentinn>（公开）｜ **触发**：`免费模型`、`free model relay`、`子代理接棒`、`模型接棒` 等（见文末触发词清单）
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
10. **开机自启 + 免费声明**（v5.7.7）— relay 随登录自动拉起（`qoder-free autostart install`），重启后不再出现「模型在列表里但请求全失败」；qoder 模型按**声明名单**写进下拉框，免费款轮换时 `sync` 会用 `stale` / `undetermined` 显式提醒。

## 安装

本仓库根目录**就是** skill 本体（v5.7.1 起改了打包方式，不再需要解 zip / 跑安装器）。任选一种方式取到目录，再整目录放进 WorkBuddy 的 skills 目录之一：

- `~/.workbuddy/skills/agentinn`（WorkBuddy 根）
- `~/.workbuddy-ai/skills/agentinn`（WorkBuddy AI 根）

**方式 A：git clone（可 `git pull` 升级）**

```bash
git clone https://github.com/2749817087qq/agentinn.git agentinn
cp -r agentinn ~/.workbuddy/skills/agentinn      # 或 ~/.workbuddy-ai/skills/agentinn
```

**方式 B：下载 tarball（无需 git）**

```bash
curl -L https://codeload.github.com/2749817087qq/agentinn/tar.gz/refs/heads/main \
  | tar xz -C /tmp && cp -r /tmp/agentinn-main ~/.workbuddy/skills/agentinn
```

**方式 C：指定版本**

```bash
git clone -b v5.7.6 --depth 1 https://github.com/2749817087qq/agentinn.git agentinn
```

装完自检：`python ~/.workbuddy/skills/agentinn/scripts/pick_model.py doctor`。

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
| `qoder-free sync` / `qoder-free status` | 刷新 / 探活 **qoderclicn 直扫**（v5.7.x 起）：agentinn 直接调用官方 `qoderclicn --list-models` 发现模型（owner=`qoderCliOwner`，url 翻转为本地 relay `http://127.0.0.1:8799/v1`，`qodercli_gateway` 保留真实网关 `https://gateway.qoder.com.cn/v1` 备查，apiKey 留空）。**不再依赖已删除的本地网关 `http://127.0.0.1:8210/v1`**。子命令名沿用历史；`status` 显示 `cli_bin` / `cli_found` / `reachable` / `models` / `relay` |
| `qoder-free relay-start` / `relay-stop` / `relay-status` | 管理 **本地 qoderclicn relay**（方案 A 落地）：relay 复用 qoderclicn 自己的浏览器会话（不逆向 token），把 OpenAI 形状请求 shell-out 到 `qoderclicn -p -m <model>` 补全。v5.7.7 起正常安装会注册**开机自启**并在登录时自动拉起，故 `relay-start` 是**兜底命令**——先 `qoder-free autostart status` 看 `registered` / `running`，都为 false 时再手动起。详见 `SKILL.md`「Qoderclicn 本地 relay」 |
| `qoder-free autostart install` / `uninstall` / `status` | **开机自启**（v5.7.7）：写平台原生启动项（Windows Startup `.vbs` / Linux XDG `.desktop` / macOS LaunchAgent），登录即拉起 relay。产物明文无凭据；`install` 幂等且不打断在用会话，`uninstall` 只摘自启不杀进程，`status` 报 `registered` / `running` / `stale` |
| `qoder-free free-set --ids <id,...>` / `free-show` / `free-reset` | **免费模型声明**（v5.7.7）：`qoderclicn --list-models` 没有免费/付费字段，故改为声明式——只有声明过的 id 才写进下拉框；无声明回落内置默认 `Qwen3.8-Flash` |
| `qoder-free sync [--all]` | 按声明刷新 `models.json`；返回 `declared` / `source` / `stale` / `undetermined` / `removed_ids`。`stale`（声明有、CLI 已无）与 `undetermined`（CLI 有、未声明）都只报不写；删除前先 `models.json.bak-<ts>` 备份，且只动 `qoderCliOwner=qoderclicn` 的条目。`--all` 显式越权写全部 |

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

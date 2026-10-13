# free-model-relay → agentinn：全量改名 + 真实可执行入口 + 数据迁移 — 技术设计

> Change: `2026-10-13-relay-agentinn-rename`｜Phase 2 SPEC｜复杂度 15/17 → `thorough`
> 基线：`23f8b7d`（relay v5.6.1）

## Context

技能 `free-model-relay` 现已具备「多模型接棒器」能力（自定义免费 + 平台内置 + 桥接源统一调度），
但名称过窄、且**无真实可执行入口**（只能写全路径 `python ~/.workbuddy/skills/free-model-relay/scripts/pick_model.py <cmd>`）。
本 change 把它改名为 `agentinn` 并提供 `agentinn` 命令。

改名面横跨 **6 个层次**（仓库内源码/文档、目录、文件名、命令入口、数据文件、所有权标记）+ **仓库外实体**
（两根安装目录、家目录数据文件、分发物）。参照本机 `rename-refactor` 规程：
**「改完不等于能用」，重心在"怎么证明改对了"。**

关键既有事实（侦察所得）：
- 源码/文档命中：`SKILL.md` 15、`relay_instruction.md` 10、`scripts/pick_model.py` 7。
- 数据文件名常量：`_STATE_NAME`/`_USAGE_NAME`/`_OVERRIDE_WIN_NAME`（L61-63）；`RELAY_OWNER_KEY`/`RELAY_OWNER_VALUE`（L3463-3464）。
- 工具名派生：`_detect_source_tool` 返回 `("relay", "free-model-relay")`（L2000/2012）。
- 现存旧数据仅 WB 根：`free-model-relay-state.json`、`free-model-relay-usage.json`。
- `models.json` 当前**无** `relayOwner` 条目。
- 其它 skill / AGENTS.md / FSTDD_CONSTITUTION.md **0 命中**。
- FSTDD 项目根 **即 skill 目录**（`.fstdd` + git 仓在其中）。

## Decisions

### D1：替换用「单次扫描 + 左边界」引擎，而非逐条 str.replace

**方案**：写一个一次性替换脚本 `tools/rename_free_model_relay.py`，规则表按「长串在前」排列，
用一条正则 alternation + 回调，**对原串只扫一遍**；每条规则加左边界 `(?<![A-Za-z])`。

**为什么**：逐条 `str.replace` 会让前一条规则的产物进入后一条的输入域（`STDD_SRC→FSTDD_SRC` 再 `STDD→FSTDD`
得 `FFSTDD_SRC`）；且重复执行会二次命中（`FSTDD→FFSTDD`）。rename-refactor 规程明列此坑。

**备选方案及排除原因**：
- 备选 A：`sed -i` 逐条替换 → 排除（同样的自匹配/顺序问题，且 Windows 无 `sed -i` 一致性）。
- 备选 B：手工逐个 Edit → 排除（>30 处，肉眼无法确认改全）。

**幂等**：脚本末尾自带幂等自测（对已改名文本再跑一次，结果不变）。

### D2：`agentinn` 入口 = 零交互转发 shim（不复制业务逻辑）

**方案**：新增 `bin/agentinn`（POSIX shell）+ `bin/agentinn.cmd`（Windows），内容仅：
解析自身位置 → 定位同目录树下的 `scripts/pick_model.py` → `exec python <script> "$@"`。
安装器把它复制到 `~/.workbuddy/bin/agentinn`（+ `.cmd`），并打印 PATH 指引。

**为什么**：单点真理（逻辑只在 `pick_model.py`）；零维护漂移；跨平台可用。

**备选方案及排除原因**：
- 备选 A：把 `pick_model.py` 重命名为 `agentinn` 并加 shebang → 排除（`pick_model.py` 被测试/文档/载荷多处按名引用，回归面大而收益低）。
- 备选 B：Python console-script（`pip install -e`）→ 排除（本项目非 pip 包，不宜给用户环境引入依赖）。

### D3：数据迁移 = 惰性「只读旧 → 写新 → 不删旧」

**方案**：在 `compute_data_paths` 得到新路径后，加一次性 `_migrate_legacy_data_files()`：
若新文件不存在且旧文件存在 ⇒ 读取旧内容写入新文件（原子写），**旧文件原样保留**（只读证据，可回滚）。
幂等：新文件存在即跳过。

**为什么**：老用户无感升级；可回滚（删新文件即回到旧状态）；不破坏「只读旧」原则。

**备选方案及排除原因**：
- 备选 A：`os.rename`（旧→新）→ 排除（不可回滚，且用户备份脚本可能依赖旧名）。
- 备选 B：不做迁移（直接换名）→ 排除（老用户状态丢失，等同硬切换）。

**三态**：旧存在→迁移；旧缺失→新建；新旧并存→以新为准（不覆盖新）。

### D4：owner 标记 = 集合判定（双值兼容）

**方案**：`RELAY_OWNER_VALUE = "agentinn"`（新写入值）；判定处改为集合
`RELAY_OWNER_VALUES = {"agentinn", "free-model-relay"}`，用 `in` 判定。
`_detect_source_tool` 的 relay 分支返回 `("relay", "agentinn")`（**报告名**统一为新名），
但**识别**仍接受旧值。

**为什么**：老 `models.json` 条目带 `relayOwner:"free-model-relay"` 不得被判 external（否则会被拒绝/覆盖，与 EXP-2026-0002 同构风险）。

**备选方案及排除原因**：
- 备选 A：只认新值 → 排除（老条目失主，破坏所有权语义）。
- 备选 B：写回时把旧值原地改写为新值 → 排除（动用户 `models.json` 内容，风险高且非必要）。

### D5：目录改名放 Phase 4 最后一步

**方案**：Phase 3 全部在旧目录名（`free-model-relay/`）下完成；DELIVER 归档后才执行
目录重命名（两根），改名后复验 CLI 可用 + git status 干净 + 载荷一致。

**为什么**：FSTDD 项目根即 skill 目录，提前改名会让 CLI（按 cwd 向上找 `.fstdd`）与 git 仓路径失配。

**备选方案及排除原因**：
- 备选 A：先建新目录、内容复制过去、最后删旧 → 排除（两份并存期间 `.fstdd`/git 双写易错）。
- 备选 B：一开始就改名再做 change → 排除（FSTDD CLI 无法定位项目根）。

### D6：排除区显式声明（历史快照保留旧名）

**方案**：排除区（不参与替换、不参与「无残留」断言）：
`.fstdd/archive/**`、`deliverables/archive/**`、`deliverables/gstack/**`、`RELEASE-AUDIT.md`、
`*.bak-*` 目录、`D:/tools/多层次agent/.workbuddy-ai/memory/**`（历史日志）。

**为什么**：这些是**历史快照/审计记录**，改了即失真（rename-refactor 明示"约 1/3 评审发现是误报"，多为把历史记录当残留）。

**每条排除给理由**，写入测试断言脚本注释。

### D7：测试策略 = 守卫测试（双向 + 文件名维度 + 幂等 + 排除区）

**方案**：新增 `tests/test-relay-agentinn-rename.py`：
- 内容维度：排除区外无 `free-model-relay` 字面（`BAD = "free-" + "model-relay"` 拼接构造，避免自检出自检）；
- 文件名维度：递归扫文件名（`find`）不含旧名；
- 正向：关键文件含 `agentinn`；
- 幂等：对已改名文本跑替换引擎两次结果一致；
- 排除区：显式断言归档仍含旧名（证明没误伤）；
- 迁移三态 + owner 双值三态（走 `pick_model.py` 真实调用，隔离 HOME）。

**为什么**：rename-refactor 明示"断言脚本自身要排除""检测串用拼接构造""文件名也要扫"。

**反向验证**：每条断言人为制造失败确认会红（防空断言）。

## Architecture

```
                 ┌─────────────────────────── 用户 / AI ───────────────────────────┐
                 │  agentinn onboard-status        （PATH: ~/.workbuddy/bin）        │
                 └───────────────┬─────────────────────────────────────────────────┘
                                 │ exec python
                                 ▼
        ~/.workbuddy/skills/agentinn/scripts/pick_model.py
                                 │
        ┌────────────────────────┼──────────────────────────┐
        ▼                        ▼                          ▼
  compute_data_paths()   RELAY_OWNER_VALUES          _detect_source_tool()
        │                 {"agentinn",              ("relay","agentinn")
        │                  "free-model-relay"}        ← 识别兼容旧值
        ▼
  _migrate_legacy_data_files()
    旧 free-model-relay-*.json ──(只读复制)──▶ 新 agentinn-*.json
    旧文件保留（只读证据 / 可回滚）
```

**改名流水线（分层，逐层验证）**：

| 切片 | 内容 | 验证方式 |
|---|---|---|
| S1 标识层 | 替换引擎改 3 个仓库内文件（内容） | 静态断言（无残留 + 新名存在） |
| S2 运行层 | `agentinn` 入口 + install.sh 安装路径 + 分发物同步 | 冒烟（真实子命令）+ 载荷一致 |
| S3 数据层 | 文件名常量 + 迁移函数 + owner 双值 | 三态测试 + 隔离 HOME |
| S4 目录层 | 两根 skill 目录改名（DELIVER 最后） | CLI 可用 + git status + 载荷复验 |

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 漏改（安装位置/文件名/仓库外） | 改完看着对、实际不能用 | 全层次枚举 + 内容&文件名双维度断言 + DELIVER 单列仓库外步骤复验 |
| 误伤历史快照 | 归档/审计失真 | 显式排除清单 + 逐条理由 + 断言「排除区仍含旧名」 |
| 替换规则自匹配/顺序 | 二次改名（FFSTDD 类） | 单次扫描 + 左边界 + 幂等自测 |
| 迁移丢数据 | 用户状态丢失 | 只读旧写新不删旧 + 三态测试 + 幂等 |
| owner 硬切换 | 老条目失主/被覆盖 | 双值集合判定 + 三态测试 |
| 目录改名破坏 FSTDD/git | CLI 失效、仓损坏 | 放最后 + 改名后复验（CLI/git/载荷） |
| PATH 未生效（Windows） | 命令找不到 | 安装器打印 PATH 指引；`.cmd` 双形态；文档给绝对路径兜底 |

## 经验库交叉检查

- **EXP-2026-0001**（context_loss/high，state 保留集）→ 数据文件迁移须确保**新 state 文件同样被「重建 state」路径读写**；
  `compute_data_paths` 是唯一路径源，改常量即全局生效，无遗漏分支。
- **EXP-2026-0002**（contract_gap/medium，复用副作用函数前核对其失败语义）→ 迁移函数**不复用**会 `_cli_fail` 的写函数，
  改用底层 `_atomic_write_json`，失败静默（不阻断主流程）。
- **EXP-2026-0003**（contract_gap/medium，载荷分叉）→ 改 `SKILL.md`/`pick_model.py` 后**必须**重跑
  `_sync_install_payload.py` + `verify_payload.py`；本 change 属"必踩区"，S2 显式纳入。

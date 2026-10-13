# 设计偏离记录 — relay-agentinn-rename

> 长程 full_auto 模式下，实施中相对 Phase 2 基线（design.md / slices.md / test-plan.md）的偏离，
> 逐条记录 **偏离内容 / 原因 / 影响 / 证据**。

## DA-1：S1 的字符串替换顺带完成了 S3 的「数据文件名常量」改名

- **偏离**：slices.md 把 `_STATE_NAME`/`_USAGE_NAME`/`_OVERRIDE_WIN_NAME` 与 `RELAY_OWNER_VALUE`
  的改名划在 S3；实际 S1 的单次扫描替换引擎在改写 `scripts/pick_model.py` 内容时，
  已把这 4 个常量（其值就是 `free-model-relay-*.json` / `free-model-relay`）一并改写。
- **原因**：常量值是「品牌名字面」，任何全量改名引擎都会命中；若要避免，必须在 S1 显式排除，
  但那样反而要维护一份「假排除」清单（S3 还会再改一次），成本更高。
- **影响**：S3 的**代码**工作量缩小为「迁移函数 + owner 双值集合 + 测试」；
  文件名常量本身无需再改（S3 仅做**验证**）。
- **证据**：`scripts/pick_model.py` L61-63 已为 `agentinn-*.json`；`RELAY_OWNER_VALUE = "agentinn"`（L3464 区）。

## DA-2：oracle 测试必须同时播种「旧名 / 新名」两个数据文件

- **偏离**：test-plan 未预见——改名后，**产品**读 `agentinn-*.json`，而冻结的 **v5.2 参考副本**
  （`tests/fixtures/pick_model-v5.2.0-reference.py`，作为活体 oracle）仍读 `free-model-relay-*.json`。
  原先「播种一个文件供产品与 oracle 共用」的写法失效。
- **原因**：oracle 是**历史快照**，不应随改名而改（改了即失去 oracle 意义）；
  但测试又想比较二者输出，于是必须给两个进程各自准备其读取的文件名。
- **影响**：
  - `tests/test-free-window-per-model.py`：`_write_override` 同时写新旧两个名字；
    `_read_override(home, name=)` 增加文件名参数，比对 oracle 时传旧名。
  - `tests/test-relay-doctor-tiers.py`：`_write_usage` 同时写新旧两个名字；
    TC-DOC-010 比较时 `cur` 读新名、`ref` 读旧名。
  - 未修前症状：TC-FWX-003 / TC-FWX-018 / TC-DOC-010 假红（oracle 读不到种子文件）。
- **证据**：修复后 `test-free-window-per-model.py` 22/22、`test-relay-doctor-tiers.py` 10/10。

## DA-3：S4 范围扩展——一并改名工作区 `deliverables/` 目录与工作区 FSTDD 项目名

- **偏离**：slices.md 的 S4 只写「分发物（文件）同步改名 + 两根 skill 目录改名」，
  未包含 `D:/tools/多层次agent/deliverables/free-model-relay/` 这个**目录名**，
  也未包含工作区 `.fstdd/config.d/project.yaml` 的 `project.name`。
- **原因**：proposal 的 **SC1 明确要求「排除区之外，全库（内容 + 文件名）无 `free-model-relay` 残留」**，
  而约束里的排除清单（`.fstdd/archive/**`、`deliverables/archive/**`、`deliverables/gstack/**`、
  `RELEASE-AUDIT.md`、`*.bak-*`、memory 历史日志）**不含** `deliverables/free-model-relay/**`。
  若不改，SC1 名义上不成立。
- **影响**（均已验证）：
  - 改名 `deliverables/free-model-relay/` → `deliverables/agentinn/`。
  - 更新引用该目录的 **39 个工作区文件**（测试 + 两个载荷工具）中的**路径上下文**
    （`skills/…`、`deliverables/…`），**不动**旧 owner 值与旧数据文件名。
  - 更新工作区 `.fstdd/config.d/project.yaml`（`name: agentinn`、`source_dir: deliverables/agentinn`）
    与 `quality.yaml`（lint/typecheck 路径）。
  - 更新 `tests/test-workspace-governance.py` TC-IDENT-001 的期望值。
- **风险控制**：替换仅针对「路径上下文」正则；已复核 `"relayOwner": "free-model-relay"`
  与 `free-model-relay-{state,usage,window}.json` 等**受保护串未被误改**。
- **证据**：`deliverables/` 与 tests 中旧名残留扫描仅剩 3 处 docstring 标题（已另行修正）。

## DA-4：`install.sh` **生成**入口（而非内嵌载荷）

- **偏离**：design.md 未指定入口的分发方式；本可把 `bin/agentinn`/`agentinn.cmd` 作为
  第 4/5 个载荷 heredoc 内嵌进 install.sh。
- **原因**：Windows 的 `.cmd` **必须是 CRLF**（LF-only 的多行 `for /d` 块会被 cmd.exe 误解析并**挂起**，
  已实测：2m+ 无输出）。而 install.sh 是 LF 的 bash 脚本，heredoc 无法携带 CRLF。
  ⇒ 入口必须由 install.sh **用 `printf '…\r\n'` 生成**（解释器与脚本路径在安装时固化）。
- **影响**：仓库内 `bin/agentinn`(+`.cmd`) 保持**可移植**（按 SKILL.md frontmatter 定位 skill 目录），
  供「直接从仓库使用 / 守卫测试」；install.sh 生成的是**部署态**入口（路径固化）。
  二者功能等价（TC-ARN-005/006 均绿）。
- **证据**：生成逻辑实测输出 `@echo off\r\n"<py>" "<skill>\\scripts\\pick_model.py" %*\r\n`（CRLF 已确认）。

## DA-5：入口按 frontmatter `name:` 定位 skill 目录（不硬编码目录名）

- **偏离**：初版 shim 用 `$BIN_DIR/../skills/agentinn` 硬编码目录名。
- **原因**：硬编码在 **S2→S4 的改名过渡期**会失效（S2 时目录还叫旧名），
  且 TC-ARN-005 以**覆盖 `HOME` 的方式**调用入口，`$HOME` 路径策略也不可用。
  改为「从 `$0` 推导前缀 → 在 `skills/*` 中找 `scripts/pick_model.py` 且 `SKILL.md` 含
  `name: agentinn`」后，改名前后均可用、且不受调用方 `HOME` 影响。
- **影响**：`bin/agentinn`（sh，glob + `grep`）与 `bin/agentinn.cmd`（cmd，`for /d` + `findstr`）。
- **证据**：S2 阶段（目录仍为旧名）TC-ARN-005/006 即已通过；S4 改名后仍通过。

## DA-6：迁移函数在 `main()` 内、dispatch 之前调用（不在 import 期）

- **偏离**：无（design.md 未指定调用点）。
- **原因**：测试常以 `exec_module` 直接加载模块并调用 `pm.cmd_window(...)` 等函数，
  若在 import 期迁移，会给只读用例引入写副作用。放在 `main()` 可保证「只有真实 CLI 调用才迁移」。
- **影响**：迁移幂等、失败静默（任何异常吞掉，绝不阻断主命令）；覆盖数据根白名单 + env 显式根。
- **证据**：`tests/test-relay-agentinn-data-migration.py` 21/21（含「旧缺失正常返回」「新旧并存以新为准」「幂等」「无 .migrating 残留」）。

## DA-7：过程纪律——回归必须**单实例**运行

- **现象**：并行跑了两个 `tests/run-all.py`，`test-scheduler-contract-and-cost.py`（30 并发 record）
  出现假挂起（25+ 进程长时间无进展）。
- **原因**：两个回归同时跑 → 并发测试互相争抢 + `test-doctor-mutation.py` **真实变异产品代码**，
  互相干扰；并非 S3 迁移引入（该测试隔离 `HOME`，迁移为 no-op；单独运行 24/24 rc=0）。
- **处置**：终止重复实例、清理卡死进程；确认产品代码**无 `MUTANT` 残留**（两根哈希一致）。
- **结论**：本 change 的回归一律单实例串行执行。

---

> 以下 DA-8 ~ DA-12 由 Phase 3 Part C1（三路并行 Review）驱动。

## DA-8：真实 HOME 指纹**限定顶层文件名集合**（不采纳 Review P2-8 的「递归」建议）

- **偏离**：Review（test_config）P2-8 指出原指纹只取顶层 `agentinn-*`/`free-model-relay-*`，
  漏掉 `models.json`；建议「纳入 models.json 及全部 `*.json`（或递归）」。
- **实施**：采纳「纳入 models.json」；**不采纳「递归 / 全部 *.json」**，改为
  `{models.json} ∪ {新旧 state/usage/window}` 的**顶层**显式集合。
- **原因**：递归会纳入 `~/.workbuddy-ai/` 下会话/缓存等**与本迁移无关、且运行期会变动**的 json，
  使 `GUARD-real-home-untouched` 因无关变动而**假红**（实测：递归版导致该守卫失败）。
  指纹的目的是「测试未污染**数据文件**」，精确限定文件名集合即可达成，且确定性强。
- **影响**：`tests/test-relay-agentinn-data-migration.py::_real_home_fingerprint`。
- **证据**：改回顶层集合后 21/21（含 GUARD）通过。

## DA-9：`_detect_source_tool` 改为**外部标记优先**，与 `models list` 口径对齐（Review P1-3）

- **偏离**：无（属 Review 发现的实现缺陷，非设计偏离）。
- **问题**：原 `_detect_source_tool` 遇 `relayOwner` 键即返回 relay，**无视同条目是否并存外部
  `*Owner`**；而 `cmd_models_list` 明确「外部标记优先」。同一「混合标记」条目在 `origins`
  与 `models list` 下结论相反，违背该函数自述的「与 list 判定口径一致，不另起一套」。
- **处置**：先收集全部 owner 键，存在任何非 `relayOwner` 键 ⇒ 按 `external`/`ow-bridge` 归类
  （与 `list` 对齐）；纯 relay 键仍按双值集合判定（SC-014/015 保持）。
- **影响**：`scripts/pick_model.py::_detect_source_tool`；回归 `test-relay-source-governance.py`
  TC-MSD-003（ow-bridge 归因）14/14 保持绿。
- **证据**：`test-relay-source-governance.py` 14/14；`test-relay-qoder-free-source.py` 19/19。

## DA-10：只读命令触发迁移**保留**（不采纳 Review P1-4 的「仅限写命令」方案），改为修订文档契约

- **偏离**：无（属 Review 指出的「文档与实现不一致」，处置方式需选择）。
- **问题**：迁移在 `main()` 中对**所有**子命令前置执行，使 `origins`/`models list`/`status`
  等自述「纯只读、不改任何文件」的命令，在存在旧名文件时会**创建新名文件**。
- **决策**：**保留**「读命令也触发迁移」——因 Phase 2 Spec **SC-010 明确规定**
  「执行任一**读取** state 的子命令（如 `status`）→ SHALL 生成 `agentinn-state.json`」，
  Review 的「仅限写命令」方案会**直接违反已确认的 Spec 基线**。
  改为修订 `cmd_origins` / `cmd_models_list` 的只读契约 docstring，显式声明
  「唯一例外：启动期一次性数据迁移（幂等、保留旧文件）」。
- **影响**：`scripts/pick_model.py` 两处 docstring（**仅注释，无行为变更**）。
- **证据**：`test-relay-agentinn-data-migration.py` TC-DFM-002（`status` 触发迁移）21/21 保持绿。

## DA-11：修复 `test-relay-source-governance.py` 子进程编码（预存缺陷）

- **偏离**：无（属预存测试缺陷，本 change 的回归暴露）。
- **问题**：该套件以 `utf-8` 解码被测子进程输出（其 docstring 自述「被测子进程的中文输出由
  run_script 以 utf-8 显式解码」），但**未给子进程设 `PYTHONIOENCODING`**；干净环境下子进程按
  locale(GBK) 输出 ⇒ utf-8 解码产生 `U+FFFD` ⇒ TC-DRA-007 的 `"数据根" in message` 断言失败，
  且失败消息回显中文时二次 `UnicodeEncodeError`。同族测试（`test-fmr-program-integration.py:102`、
  `test-fmr-doc-sample.py:110` 等）均**显式设 `env["PYTHONIOENCODING"]="utf-8"`**，本套件是遗漏。
- **处置**：在 `run_script` 中为子进程设 `PYTHONIOENCODING=utf-8`，与下方 utf-8 解码自洽。
- **影响**：`tests/test-relay-source-governance.py`（测试代码，非产品）。
- **证据**：修复后干净环境 14/14 rc=0（修复前 rc=1）。

## DA-12：守卫套件加固（Review test P1-1 / code P1-1 + 若干 P2）

- **偏离**：无（属 Review 驱动的测试加固）。
- **内容**：
  - **P1-1（覆盖盲区）**：TC-ARN-001 增加 `TC-ARN-001d` 扫描 `deliverables/agentinn/`
    （排除历史快照 `RELEASE-AUDIT.md`）；新增 `_is_text()` 判定（白名单扩展名 **或** 无扩展名且
    UTF-8 可解码），消除「无扩展名文件（`bin/agentinn`）被静默跳过」的假绿。
  - **P2-1/P2-3**：`_run` / TC-ARN-005 直调分支补 `stdin=subprocess.DEVNULL`（防挂起双保险）。
  - **P2-2**：删除死代码 `run_cli`。
  - **P2-4**：TC-ARN-003b 改为 fail-closed（基目录全缺 ⇒ 判红）。
  - **P2-5**：TC-ARN-002a 限定在首个 `--- … ---` frontmatter 块内解析 `name`。
- **证据**：守卫套件由 15 检查增至 **16 检查**，全部通过；`deliverables/` 旧名残留（除
  `RELEASE-AUDIT.md`）为 0。

---

> 以下 DA-13 记录 DELIVER 期（归档时）的编号决策。

## DA-13：本 change 的两个 capability 采用 **change 内全局 SC 编号**（SC-001~016），不重编

- **背景**：Phase 2 为本 change 的两个 capability 用了 change 内**全局** SC 序号——
  `agentinn-rename` = SC-001~008，`data-file-migration` = SC-009~016。项目其它 7 个 capability 的
  `specs/<cap>/spec.md` 均**从 SC-001 起**。DELIVER 期发现该差异，评估是否重编。
- **决策**：**不重编**，保持 SC-009~016。理由：
  1. **无实际冲突**：SC 编号是 **per-capability 命名空间**（每个 `specs/<cap>/spec.md` 独立定义）；
     `agentinn-rename` 与 `data-file-migration` 均为**本 change 新建** capability，SC-009~016
     不与任何**既有** capability 的编号发生同文件冲突。此前 v5.6.1 需重编（SC-011/012→SC-012/013）
     是因该 change 向**已存在**的 `unified-onboarding` **追加** Scenario、与既有 SC-011 撞号——
     本次不存在该条件。
  2. **内部已自洽**：`specs/<cap>/spec.md` ↔ `canonical/specs/{agent,code}/<cap>.yaml` ↔
     产品 docstring（`_migrate_legacy_data_files` 注明 `SC-010/012/013`）↔ test-plan ↔ 测试，全部一致。
  3. **归档不可变**：`archive` 已把 change 快照落盘；重编须同时改写**归档快照**（否则 live 与 archive
     分叉），违反「归档即历史真相」原则。正确重编时机是 Phase 2（Gate 2 前），现已错过。
  4. **收益为零、风险非零**：重编需改动产品代码 docstring ⇒ 重同步载荷 ⇒ 重跑全量回归，纯形式收益。
- **影响**：无功能影响；作为已知的编号风格差异记录在案。后续新 capability 建议一律从 SC-001 起。
- **证据**：`fstdd validate` rc=0、`canon verify` 2/2 均通过；各 capability SC 范围实测（见 test-report）。

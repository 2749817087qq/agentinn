# 测试报告 — relay-agentinn-rename（v5.7.0 改名版）

> Change: `2026-10-13-relay-agentinn-rename`
> 模式：thorough（长程 full_auto）｜ 生成于 Phase 3 Part C（C7）
> 基线 commit：`23f8b7d1966e02b9fa683ff089b3ff539d691ece`（relay v5.6.1）

## 一、TC 覆盖率（planned vs actual）

| 项 | 计划 | 实际 | 说明 |
|----|------|------|------|
| TC 案例数 | 16（TC-ARN-001~008 + TC-DFM-001~008） | **16** | 无增补、无删减 |
| 新增测试脚本 | 2 | **2** | `test-relay-agentinn-rename.py`（守卫）、`test-relay-agentinn-data-migration.py`（迁移） |
| 断言检查点 | — | **37**（守卫 16 + 迁移 21） | TC→检查点非 1:1（如 TC-ARN-001 含 a/b/c/d） |
| Scenario 覆盖 | 16（SC-001~016） | **16/16** | 每个 SC 至少 1 个 TC（见覆盖矩阵） |
| 修改既有测试 | — | **4** | `test-free-window-per-model.py`、`test-relay-doctor-tiers.py`（oracle 双播种，DA-2）；`test-workspace-governance.py`（项目名期望）；`test-relay-source-governance.py`（子进程编码，DA-11） |
| 全量回归 | 28 脚本 | **28/28 rc=0** | 含 2 个新脚本；无回归 |

**实测输出**：
- `tests/test-relay-agentinn-rename.py` → `result: 16 passed, 0 failed, 16 total`
- `tests/test-relay-agentinn-data-migration.py` → `result: 21 passed, 0 failed, 21 total`
- `tests/run-all.py` → `全部 28 个测试脚本 rc=0`（耗时 13m23s）

## 二、切片验证状态（B3.4）

| 切片 | 实现目标 | TC 覆盖 | 新增检查点 | 状态 |
|------|---------|---------|-----------|------|
| S1 标识层 | 品牌名替换（内容 + frontmatter + 文档示例） | TC-ARN-001/002/004/008 | 4 | ✅ done |
| S2 入口层 | `bin/agentinn`(+`.cmd`) + 安装到两根 `bin/` | TC-ARN-005/006 | 2 | ✅ done |
| S3 数据层 | `_migrate_legacy_data_files` + owner 双值集合 + 判定 | TC-DFM-001~008 | 8 | ✅ done |
| S4 分发与目录层 | 39 文件路径迁移 + `deliverables/` 与两根目录改名 + install.sh 入口生成 + 载荷重同步 | TC-ARN-003/007 | 2 | ✅ done |

合计 4 切片，逐切片验证均通过（TC 覆盖 100% + 产出物核对 + 测试通过），记录于 `.fstdd.yaml::phases.build.slices_completed`。

## 三、失败模式检查（C4，全量执行）

### 3.1 CLI 确定性子集（`fstdd ci check-failures`）

| 项 | 结果 | 说明 |
|----|------|------|
| (a) 必需文件存在 + Spec 文件存在 | ✅ PASS | — |
| (f) 所有 THEN 含 SHALL | ✅ PASS | — |
| (k) 契约一致 | ✅ PASS | 2 capabilities 一致 |
| 切片验证证据 | ✅ PASS | 4 个切片均有 tc_coverage/new_tests/verified_at |
| (b) proposal 声明 capability 列表 | ⏭ SKIP | 前置产物在 Phase 4 canonical 合并后生成（见「已知问题 3」） |
| (j) 覆盖真空 | ⏭ SKIP | 无 coverage.json（见「已知问题 4」） |
| TC 实现覆盖 | ⏭ SKIP | `tests/` 位于工作区，不在 skill 项目根下（见「已知问题 4」） |
| (l) 锚定检查 | ⏭ SKIP | canonical proposal 在 change 目录（见「已知问题 3」） |
| (g) AND 超限 | ⚠ WARN | **构造性误报**（见「已知问题 2」） |
| (d) TC-ID 唯一 | ❌ FAIL | **构造性误报**（见「已知问题 1」） |

### 3.2 14 类失败模式（语义检查，逐项执行）

| # | 失败模式 | 结果 | 检查动作与证据 |
|---|---------|------|---------------|
| 1 | 幻觉调用 | ✅ | AST 复扫：`_legacy_data_name`/`_migrate_legacy_data_files`/`RELAY_OWNER_VALUES`/`RELAY_OWNER_LEGACY_VALUE`/`_DATA_NAME_PREFIX`/`_LEGACY_DATA_PREFIX` 均有定义且有消费方；`bin/agentinn` 引用真实 `scripts/pick_model.py`；无 `breakpoint()/pdb/TODO/FIXME` |
| 2 | 过度信任 LLM | ✅ | 全部结论基于实跑：回归 28/28 rc=0、载荷 emb==auth、守卫 16/16、迁移 21/21 |
| 3 | Prompt 注入 | ✅ | 未改 system prompt；文档改动仅品牌词与命令面；无 `ignore previous` / `you are now` 类注入痕迹 |
| 4 | 记忆污染 | ✅ | 独立 change 目录；未复用旧会话上下文 |
| 5 | 上下文窗溢出 | ✅ | 单次 Edit 均 < 60 行；`pick_model.py` 净增 16 行 |
| 6 | 工具参数漂移 | ✅ | 入口为纯转发（无新参数）；`agentinn <cmd>` 与直调逐字等价（TC-ARN-005） |
| 7 | 安全凭证泄露 | ✅ | 本 change 不读写密钥；`models add/list` 遮蔽逻辑未动；`test-cred-security.py` 4/4；无 token/key 硬编码（`sk-xxx` 命中属占位符黑名单） |
| 8 | 权限绕过 | ✅ | 未手改 `.fstdd.yaml` 的 `confirmed_*`（STDD Guard 未触发）；Gate 走正规 CLI |
| 9 | 并发竞态 | ✅ | 迁移临时名带 pid（DA-9/P2-1）；`test-lock-concurrency.py` 6/6；回归单实例（DA-7） |
| 10 | 路径遍历 | ✅ | 数据根来自固定白名单（`.workbuddy`/`.workbuddy-ai`）+ env 显式根；无 `../` 逃逸 |
| 11 | 跨会话残留 | ✅ | 测试 `finally` 清理临时 HOME；`GUARD-real-home-untouched` 通过（真实家目录数据文件指纹前后一致） |
| 12 | 输出截断 | ✅ | 各命令输出为小 JSON；无大 payload hook 输入 |
| 13 | 格式错误 | ✅ | `fstdd validate` rc=0；`canon verify` 2/2；迁移产物 JSON 合法（TC-DFM 实读校验） |
| 14 | 循环依赖 | ✅ | `fstdd dependency-graph`：Nodes=2, Edges=0, 无环；未新增 import |
| 15~22 | 金融红线联动（重复扣款/账实不符/静默降级/精度丢失/审计缺口/状态机/额度穿透/合规） | N/A | Step 0.5 判定 `FINANCIAL_PROJECT=NO`（无支付/交易/资金/风控关键词），不适用 |

## 四、Diff 审查（C3）

基线 `23f8b7d` → 工作区（skill 仓 5 改 + 3 新增目录）：

| 文件 | 变更 | 审查结论 |
|------|------|---------|
| `scripts/pick_model.py` | 99 行净变（品牌名 / 数据文件名常量 / 迁移函数 / owner 双值集合 / `_detect_source_tool` / `main()` 钩子） | ✅ 无调试残留、无死代码；迁移幂等、以新为准、保留旧；owner 判定与 `list` 对齐 |
| `SKILL.md` | 173 行净变（品牌名 + `$PY $SCRIPT` → `agentinn`） | ✅ 模板块 `relay-onboarding-wizard` / `relay-window-wheel` 成对完好；示例统一 `agentinn <cmd>` |
| `relay_instruction.md` | 20 行净变（品牌名 + 命令面） | ✅ 四步接棒示例统一 `agentinn <cmd>` |
| `.gitattributes` | +4 行（`*.cmd`/`*.bat` eol=crlf） | ✅ 修复 Windows 入口检出后变 LF 的隐性破坏 |
| `.fstdd/config.d/project.yaml` | `name: stdd`→`agentinn`、`source_dir: app`→`.` | ✅ 项目根配置对齐 |
| `bin/`（新） | `agentinn`(sh) + `agentinn.cmd`(CRLF, ASCII) | ✅ 纯转发、零业务逻辑；`.cmd` 实测 0 LF-only / 43 CRLF |
| `tools/`（新） | `rename_to_agentinn.py` 单次扫描替换引擎 | ✅ 幂等、左边界、拼接构造旧名 |
| `.fstdd/changes/…`（新） | 本 change 全套 FSTDD 工件 | ✅ — |

**分发物**（`deliverables/agentinn/`）：`install.sh`（318605 B，含迁移 + 6.5 入口生成）、`agenthub-install.sh`（与 install.sh 字节副本）、`README.md`（行数/命令面）、`verify_payload.py` 等。`verify_payload.py` 实测三份 heredoc emb==auth、两根 `SKILL.md`/`relay_instruction.md`/`pick_model.py` 字节一致。

## 五、功能/测试覆盖对照

| 功能模块 | 涉及源码 | 已有测试覆盖 | 缺失测试 |
|---------|---------|-------------|---------|
| 标识/文档改名 | `SKILL.md`、`relay_instruction.md` | TC-ARN-001/002 | 无 |
| 文件名维度 | 两根 skill 目录 + 数据文件名 | TC-ARN-003 | 无 |
| 替换引擎 | `tools/rename_to_agentinn.py` | TC-ARN-004 | 无 |
| agentinn 入口 | `bin/agentinn`(+`.cmd`)、install.sh 6.5 | TC-ARN-005/006 | shape-2 分支无独立覆盖（见已知问题 5） |
| 目录改名 | 两根 `skills/`、`deliverables/` | TC-ARN-007/001d | 无 |
| 历史快照 | 归档/审计/日志 | TC-ARN-008 | 无 |
| 数据迁移 | `_migrate_legacy_data_files` | TC-DFM-001~005 | 无 |
| owner 兼容 | `RELAY_OWNER_VALUES`、`_detect_source_tool` | TC-DFM-006~008 | 无 |

## 五-B、多路并行 Review 结果（C1）

> 由 3 代理并行审查（code / test_config / docs_skills），全程只读。报告存于
> `D:/tools/多层次agent/deliverables/agentinn-review-{code,test,docs}-2026-10-13.md`。

### Review 迭代历史

| 轮次 | C(P0) | H(P1) | M(P2) | L | 状态 |
|------|---|---|---|---|------|
| 1 | 0 | 8 | 25 | 0 | **需修复（P1）** → 已修复 8/8 P1 + 11 P2 |

### 最终 Review 汇总

| 维度 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 代码质量 | 0 | 4 | 9 | 0 | 13 |
| 测试/配置 | 0 | 2 | 8 | 0 | 10 |
| 文档/Skills | 0 | 2 | 8 | 0 | 10 |
| **合计** | **0** | **8** | **25** | **0** | **33** |

### Review 已修复问题（8×P1 全修 + 11×P2）

| # | 严重性 | 文件 | 问题 | 状态 |
|---|--------|------|------|------|
| 1 | P1 | `bin/agentinn:10` | 旧名残留 + 守卫无扩展名盲区 | ✅ 已修复（注释改写 + `_is_text`） |
| 2 | P1 | `.gitattributes` | 缺 `*.cmd eol=crlf` | ✅ 已修复 |
| 3 | P1 | `pick_model.py::_detect_source_tool` | 与 `models list` 混合标记口径相反 | ✅ 已修复（外部标记优先，DA-9） |
| 4 | P1 | `pick_model.py`（只读 docstring） | 只读命令被前置迁移写盘（文档/实现冲突） | ✅ 已修复（保留行为 + 修订 docstring，DA-10） |
| 5 | P1 | `tests/test-relay-agentinn-rename.py` | 守卫未扫 `deliverables/` + 跳过无扩展名 | ✅ 已修复（TC-ARN-001d + `_is_text`） |
| 6 | P1 | skill `.fstdd/config.d/project.yaml` | `name: stdd` 未对齐 | ✅ 已修复（`agentinn` / `source_dir: .`） |
| 7 | P1 | `deliverables/agentinn/agenthub-install.sh` | 与 install.sh 载荷分叉（陈旧） | ✅ 已修复（字节副本刷新） |
| 8 | P1 | `deliverables/agentinn/README.md` | 常用命令用不存在的 `relay` | ✅ 已修复（`agentinn <cmd>`） |
| 9~19 | P2 | 见 design-adjustments DA-8/DA-12 及各文件 | 临时名并发、根收集异常、测试防挂起/fail-closed/frontmatter、README 行数、SKILL.md:215、游离空文件、指纹覆盖 models.json | ✅ 已修复（11 项） |

### Review 已知限制（未修复，择期处理）

| # | 严重性 | 文件 | 问题 |
|---|--------|------|------|
| 1 | P2 | `bin/agentinn` / `install.sh:6.5` | shape-2 定位分支在交付路径无独立测试覆盖；两套入口实现（见已知问题 5） |
| 2 | P2 | `bin/agentinn:37` | 裸 glob 扫 `skills/*` 未显式排除 `.bak-*`（当前实际不误命中：备份目录 frontmatter 为旧名） |
| 3 | P2 | `bin/agentinn:57` / `install.sh:35` | 回退解释器硬编码 `C:/Python311/python.exe`（环境相关） |
| 4 | P2 | `_sync_install_payload.py:14-15` | 硬编码本机绝对路径（一次性维护脚本） |
| 5 | P2 | `install.sh` 6.5 生成入口 | 混用 `/` 与 `\` 分隔符（实测可用，健壮性建议） |
| 6 | P2 | `bin/agentinn:39` / `.cmd:33` | frontmatter 前缀匹配（`agentinn-extra` 亦命中，实际不可达） |
| 7 | P2 | `deliverables/agentinn/RELEASE-AUDIT.md` | 历史审计快照仍含旧名（**有意保留**，与 archive 同策略） |
| 8 | P2 | `tests/probe-*.py` | 3 个 probe 硬编码旧数据文件名（probe 为实验件；`probe-regression-assertions.py` 已退化，待另立 change 修） |
| 9 | P2 | `tests/test-relay-agentinn-data-migration.py` | `_load_module` 在真实 HOME 下 in-process 导入（隔离缝隙） |
| 10 | P2 | `deliverables/agentinn/README.md` | 包版本行 `v5.6.0` 待 Phase 4 bump 刷新 |
| 11 | P2 | `deliverables/agentinn/ROADMAP.md:161` | 历史实测块用裸脚本名（保留原文有理由） |
| 12 | P2 | `deliverables/agentinn/README.md:1` | 包名 `agenthub` 与技能名 `agentinn` 并存（建议顶部澄清） |

## 六、设计调整说明（C6）

本次共记录 **12 条设计偏离**（DA-1~DA-12）：S1 顺带完成 S3 常量改名（DA-1）、oracle 双播种（DA-2）、
S4 范围扩展（DA-3）、install.sh 生成入口（DA-4）、入口按 frontmatter 定位（DA-5）、迁移在 `main()`
调用（DA-6）、单实例回归纪律（DA-7）、指纹限定顶层（DA-8）、`_detect_source_tool` 对齐（DA-9）、
只读命令保留迁移（DA-10）、source-governance 编码修复（DA-11）、守卫加固（DA-12）。
详见 [design-adjustments.md](design-adjustments.md)。

## 七、修复确认记录

| 问题 | 修复文件 | 状态 |
|------|----------|------|
| `bin/agentinn:10` 旧名注释 | `bin/agentinn`（4 处镜像） | ✅ |
| `.cmd` 行尾 | `.gitattributes` | ✅ |
| 混合标记口径漂移 | `scripts/pick_model.py::_detect_source_tool` | ✅ |
| 只读契约文档 | `scripts/pick_model.py`（2 docstring） | ✅ |
| 守卫盲区 | `tests/test-relay-agentinn-rename.py` | ✅ |
| 技能根项目名 | `.fstdd/config.d/project.yaml` | ✅ |
| `agenthub-install.sh` 陈旧 | `deliverables/agentinn/agenthub-install.sh` | ✅ |
| README 命令面 | `deliverables/agentinn/README.md` | ✅ |
| oracle 播种 | `test-free-window-per-model.py`、`test-relay-doctor-tiers.py` | ✅ |
| 子进程编码 | `tests/test-relay-source-governance.py` | ✅ |
| 游离空文件 `skill` | 两根目录 | ✅ 删除 |

## 七-B、经验库更新（C5）

### 本次新增经验

| 经验ID | 类别 | 模式 | 严重程度 | 发现阶段 |
|--------|------|------|---------|---------|
| EXP-2026-0004 | test_blind_spot | 改名守卫按扩展名过滤 ⇒ 无扩展名入口被跳过 ⇒ 假绿 | high | BUILD |
| EXP-2026-0005 | test_gap | 测试以 utf-8 解码子进程输出却不强制子进程 utf-8 ⇒ 干净环境假红 | medium | BUILD |
| EXP-2026-0006 | contract_gap | 冻结 oracle 不随改名而改 ⇒ 数据文件名变更后单份种子失效 | medium | BUILD |

### 本次命中已有经验（复用）

| 经验ID | 类别 | 模式 | 命中阶段 |
|--------|------|------|---------|
| EXP-2026-0003 | contract_gap | 改了 install.sh 内嵌源文件后未重跑载荷同步 ⇒ 载荷分叉连锁失败 | BUILD（编辑 `pick_model.py`/`SKILL.md` 后即重跑 `_sync_install_payload.py` + `verify_payload.py`） |

### 经验统计

| 指标 | 数值 |
|------|------|
| 本次新增 | 3 条 |
| 本次复用 | 1 条 |
| 经验库总计 | 6 条 |

> 经验库索引：`.fstdd/experiences/.experience-index.yaml`

## 八、结论

**可以进入 Gate 3。** 8 项 P1 全部修复；11 项 P2 已修复，14 项 P2 记为已知限制（多为环境相关/历史件/
健壮性建议，不阻断）。核心交付（改名完整性、入口等价、数据迁移幂等、owner 双值兼容）经静态守卫 +
集成 + 冒烟三层验证，且全量回归 28/28 rc=0。风险等级：**低**。

### 8.1 质量信号汇总

| 信号源 | 状态 | 备注 |
|--------|------|------|
| 单元/集成测试 | ✅ | 回归 28/28 rc=0（新增 2 脚本：守卫 16/16、迁移 21/21） |
| E2E 测试 | N/A | 项目未启用 `quality.e2e`；等价性由 TC-ARN-005/006 冒烟覆盖 |
| Lint | ✅ | `test-maintainability-fixes.py` 通过 |
| 类型检查 | N/A | 项目未强制 mypy |
| 多版本测试 | N/A | 单 Python 版本（3.11.9） |
| 覆盖率 | N/A | 无 coverage.json（诊断缺省） |
| 十四类失败模式 | ✅ | 命中 0 项 P0；15~22 金融红线 N/A |

## 九、已知问题（逐项说明）

1. **(d) 重复 TC-ID（❌ FAIL）— 构造性误报**。`ci.py:317` 用 `re.findall(r"TC-[A-Z]+-\d{3}", test-plan.md)`
   统计**出现次数**（本 change 实测 42 次 / 16 个唯一 ID / 16 个定义行），任何 ID 出现 >1 次即判重复；
   而 test-plan 的覆盖矩阵/补充顺序本就合法引用 ID。对照 `validate.py:79` 已改用「仅统计案例定义行
   `| **ID** | TC-XXX-001 |`」并因此通过——`ci.py` 未同步该修复。**无真正重复定义**，记录为 CLI 缺陷。
2. **(g) AND 超限（⚠ WARN）— 构造性误报**。`ci.py` 按**整份 spec.md** 累计 AND 数量（本次 8），
   而非按单个 Scenario；本项目任一含 ≥2 Scenario 的 spec 必然触发。单 Scenario AND 均 ≤3（限 5）。
3. **(b)/(l) SKIP — 前置产物在 Phase 4 才生成**。(l) 读**项目级** `.fstdd/canonical/proposals/<change>.yaml`，
   本 change 的 canonical 目前位于 change 目录；(b) 依赖 proposal 的 capability 列表（同上）。
   两者均在 Phase 4 DELIVER 的「canonical 合并」补齐，**非缺陷**。
4. **(j)/TC 实现覆盖 SKIP — 结构性**。项目无 coverage.json；`tests/` 位于工作区
   `D:/tools/多层次agent/tests`，不在 skill 项目根下，CLI 探测不到。TC 实现覆盖由本报告第一节以实测替代。
5. **入口两套实现（shape-2）**。仓库 `bin/agentinn` 含「按 frontmatter 定位」逻辑，而 install.sh 6.5
   生成**路径固化**的简化版；TC-ARN-005/006 只测安装位（生成的简化版）。当前二者功能等价，但存在
   漂移风险，记为已知限制。

## 十、未完成项

- **无阻塞性未完成项**。C1~C7 全部完成。
- 版本号 bump（`SKILL.md` `version` 5.6.1 → 5.7.0、`build_agenthub.py 5.7.0` 重打包、README 包版本行）：
  按流程在 **Phase 4 DELIVER** 执行。
- 已知限制 12 项（上表）为择期项，非本 change 范围。

## 十一、证据记录

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| 守卫套件 16/16 通过 | 2026-10-13T09:52:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `tests/test-relay-agentinn-rename.py` |
| 数据迁移 21/21 通过 | 2026-10-13T09:52:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `tests/test-relay-agentinn-data-migration.py` |
| 全量回归 28/28 rc=0 | 2026-10-13T09:57:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `tests/run-all.py` |
| 载荷 emb==auth + 双根字节一致 | 2026-10-13T09:47:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `deliverables/agentinn/verify_payload.py` |
| `canon verify` 2/2 | 2026-10-13T09:35:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `fstdd canon verify` |
| `validate` rc=0 / `ci` 4PASS | 2026-10-13T09:35:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `fstdd validate` / `ci check-failures` |
| `dependency-graph` 无环 | 2026-10-13T09:58:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `fstdd dependency-graph` |

- `observed_at` 是**信息采集时刻**，非文档生成时刻。

# 测试报告 — relay-v561-agenthub-wiring（v5.6.1）

> Change: `2026-10-12-relay-v561-agenthub-wiring`
> 模式：standard（长程 full_auto）｜ 生成于 Phase 3 Part C（C7）
> 基线 commit：`21c7f0fd912dc515857b3aaa093ba08c84a6c4cd`（relay v5.6.0）

## 一、TC 覆盖率（planned vs actual）

| 项 | 计划 | 实际 | 说明 |
|----|------|------|------|
| TC 案例数 | 12（TC-AW-001~012） | **13**（+TC-AW-013） | TC-AW-013 为 BUILD 期评审（DA-1）增补 |
| 新增测试函数 | 12 | **13** | 与 TC 1:1 |
| 测试脚本 | 1（`test-relay-agenthub-wiring.py`） | 1 | 13/13 通过 |
| Scenario 覆盖 | 12 | 12/12 | 每个 SC 至少 1 个 TC |
| 全量回归 | 26 脚本 | **26/26 rc=0** | 含新增脚本；无回归 |

**实测输出**：`tests/test-relay-agenthub-wiring.py` → `result: 13 passed, 0 failed, 13 total`；
`tests/run-all.py` → `全部 26 个测试脚本 rc=0`。

## 二、切片验证状态（B3.4）

| 切片 | 实现目标 | TC 覆盖 | 新增测试 | 状态 |
|------|---------|---------|---------|------|
| S1 | `_agenthub_action()` + `_onboard_agenthub_view()` 增 `action`/`prompted_on` | TC-AW-001~004,011 | 5 | ✅ done |
| S2 | `cmd_onboard_agenthub_ack()` + `_dispatch_onboard` 分支 + CLI 枚举 | TC-AW-005~007,**013** | 4 | ✅ done |
| S3 | `cmd_onboard_set` carry-over + 策略切换保留 | TC-AW-010,012 | 2 | ✅ done |
| S4 | `relay_instruction.md` + `SKILL.md` 联动规则（双根） | TC-AW-008~009 | 2 | ✅ done |

合计 13 个新增测试，逐切片验证均通过（TC 覆盖 100% + 产出物核对 + 测试通过）。

## 三、失败模式检查（C4，全量执行）

### 3.1 CLI 确定性子集（`fstdd ci check-failures`）

| 项 | 结果 | 说明 |
|----|------|------|
| (a) 必需文件存在 + Spec 文件存在 | ✅ PASS | — |
| (f) 所有 THEN 含 SHALL | ✅ PASS | — |
| (k) 契约一致 | ✅ PASS | 2 capabilities 一致 |
| 切片验证证据 | ✅ PASS | 4 个切片均有 tc_coverage/new_tests/verified_at |
| (b) proposal 声明 capability 列表 | ⏭ SKIP | 见「已知问题 3」 |
| (j) 覆盖真空 | ⏭ SKIP | 无 coverage.json（见「已知问题 4」） |
| TC 实现覆盖 | ⏭ SKIP | 见「已知问题 4」 |
| (l) 锚定检查 | ⏭ SKIP | 见「已知问题 3」 |
| (g) AND 超限 | ⚠ WARN | **构造性误报**（见「已知问题 2」） |
| (d) TC-ID 唯一 | ❌ FAIL | **构造性误报**（见「已知问题 1」） |

### 3.2 14 类失败模式（语义检查，逐项执行）

| # | 失败模式 | 结果 | 检查动作与证据 |
|---|---------|------|---------------|
| 1 | 幻觉调用 | ✅ | 审查 diff：`AGENTHUB_PROMPTED_KEY` / `_agenthub_action` / `cmd_onboard_agenthub_ack` 均有定义且有消费方；无未 import 符号 |
| 2 | 过度信任 LLM | ✅ | 全部结论基于实跑：回归 26/26 rc=0、载荷 emb==auth、13/13 TC 实测 |
| 3 | Prompt 注入 | ✅ | 未改 system prompt；两份文档新增规则无 `ignore previous` / `you are now` 类注入痕迹 |
| 4 | 记忆污染 | ✅ | 独立 change 目录；未复用旧会话上下文 |
| 5 | 上下文窗溢出 | ✅ | 单次 Edit 均 < 300 行；改动集中在 ~120 行内 |
| 6 | 工具参数漂移 | ✅ | 仅用既有 CLI（`onboard` / `onboard-status`）；新增 action 遵循既有 argparse 位置参数惯例 |
| 7 | 安全凭证泄露 | ✅ | `test-cred-security.py` 4/4 通过；本 change 不读写密钥；新增代码无 token/key 硬编码 |
| 8 | 权限绕过 | ✅ | 未手改 `.fstdd.yaml` 的 `confirmed_*` 字段（STDD Guard 未触发）；Gate 走正规 CLI |
| 9 | 并发竞态 | ✅ | ack 复用 `state_file_lock()`；`test-lock-concurrency.py` 6/6 通过 |
| 10 | 路径遍历 | ✅ | 无外部路径输入；state 路径由既有常量决定；无 `../` 逃逸 |
| 11 | 跨会话残留 | ✅ | 测试 `finally` 清理临时 HOME；无 `.tmp` / `.scratch` 残留 |
| 12 | 输出截断 | ✅ | ack 输出为小 JSON；无大 payload hook 输入 |
| 13 | 格式错误 | ✅ | `fstdd validate` 通过；`canon verify` 2/2；输出 JSON 合法 |
| 14 | 循环依赖 | ✅ | `dependency-graph` cycles=[]；未新增 import |
| 15~22 | 金融红线联动（重复扣款/账实不符/静默降级/精度丢失/审计缺口/状态机/额度穿透/合规） | N/A | Step 0.5 判定 `FINANCIAL_PROJECT=NO`（无支付/交易/资金/风控等关键词），不适用 |

## 四、Diff 审查（C3）

| 文件 | 变更 | 审查结论 |
|------|------|---------|
| `scripts/pick_model.py` | +6 处（常量 / `_agenthub_action` / view 扩展 / ack / 分派 / carry-over / CLI 枚举） | ✅ 无调试残留、无死代码、无注释掉的旧逻辑；与 spec 一致 |
| `SKILL.md` | +18 行（AgentHub 接线小节） | ✅ 模板块 `relay-onboarding-wizard:start/end` 完好 |
| `relay_instruction.md` | +10 行（Step 0 联动规则） | ✅ 与 SKILL.md 规则一致 |
| `tests/test-relay-agenthub-wiring.py` | 新增 13 TC | ✅ 隔离 HOME + 冻结时钟 + ASCII 断言 + 真实 HOME 守卫 |
| `install.sh` | 载荷重同步（3 段） | ✅ `verify_payload.py` emb==auth、双根字节一致 |

## 五、已知问题（逐项说明）

1. **(d) 重复 TC-ID（❌ FAIL）— 构造性误报**。
   实现：`ci.py:317` 用 `re.findall(r"TC-[A-Z]+-\d{3}", test-plan.md)` 统计**出现次数**，任何 ID 出现 >1 次即判重复。
   test-plan.md 中每个 TC 有**唯一**的 `| **ID** | TC-AW-NNN |` 定义行；其余出现均为交叉引用（覆盖矩阵 / 补充顺序 / 区间写法 `TC-AW-001~004`）。
   故**无真正重复定义**。判定为 CLI 检查口径缺陷（与既有 (g) AND 计数同类）。**记录为已知问题，不修改文档**。

2. **(g) AND 超限（⚠ WARN）— 构造性误报**。
   `ci.py` 按**整份 spec.md** 累计 AND 数量（本次 8），而非按单个 Scenario 计数；本项目任一含 ≥2 Scenario 的 spec 必然触发。单 Scenario 的 AND 均 ≤3（限 5）。**记录为已知问题**。

3. **(b) / (l) SKIP — 前置产物在 Phase 4 才生成**。
   (l) 读**项目级** `.fstdd/canonical/proposals/<change>.yaml`，本 change 的 canonical 目前位于 change 目录；
   (b) 依赖 proposal 的 capability 列表（同上）。
   两者均在 Phase 4 DELIVER 的「canonical 合并」步骤补齐，**非缺陷**。

4. **(j) / TC 实现覆盖 SKIP — 结构性**。
   项目无 coverage.json（未启用 pytest-cov）；且 `tests/` 位于工作区 `D:/tools/多层次agent/tests`，
   不在 skill 项目根下，CLI 探测不到。TC 实现覆盖由本报告第一节以实测替代（13/13）。**记录为已知问题**。

## 六、未完成项

- **无阻塞性未完成项**。C1~C7 全部完成。
- 版本号 bump（`SKILL.md` frontmatter `version` → 5.6.1）：按流程在 **Phase 4 DELIVER** 执行（文档评审已确认属预期）。
- 后续可选（非本 change 范围）：SKILL.md「使用流程」Step 0/1 仍描述 v5.6.0 前旧两段式，建议另立 change 收敛。

## 七、证据记录

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| 新套件 13/13 通过 | 2026-10-12T16:51:22+00:00 | 21c7f0fd912dc515857b3aaa093ba08c84a6c4cd | `tests/test-relay-agenthub-wiring.py` |
| 全量回归 26/26 rc=0 | 2026-10-12T16:51:22+00:00 | 21c7f0fd912dc515857b3aaa093ba08c84a6c4cd | `tests/run-all.py` |
| 载荷 emb==auth + 双根字节一致 | 2026-10-12T16:44:00+00:00 | 21c7f0fd912dc515857b3aaa093ba08c84a6c4cd | `deliverables/free-model-relay/verify_payload.py` |
| canon verify 2/2 | 2026-10-12T15:37:00+00:00 | 21c7f0fd912dc515857b3aaa093ba08c84a6c4cd | `fstdd canon verify` |

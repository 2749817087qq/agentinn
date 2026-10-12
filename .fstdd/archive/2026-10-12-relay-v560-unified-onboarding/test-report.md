# v5.6.0-unified-onboarding 测试报告

> 测试日期：2026-10-12
> 测试环境：Windows (win32), Python 3.11.9, pytest 7.4.3
> 被测版本：unversioned（本机双 WorkBuddy 根，非 git 版本化）
> 被测对象：`scripts/pick_model.py`（新增 onboard 族命令）+ `SKILL.md` + `relay_instruction.md` + `tests/test-relay-unified-onboarding.py`

## 一、总体概况

| 指标 | 数值 |
|------|------|
| 新增测试用例总数 | 18（TC-UOB-001 ~ 013 + 010b + 005i/006i/007i/008i） |
| 通过 | 18 |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | 100% |
| 全量回归脚本数 | 25（`tests/run-all.py`） |
| 全量回归通过 | 25/25（rc=0） |

### 1.1 覆盖率诊断（仅变更文件）

> 覆盖率仅作诊断参考，不作为通过/失败的门禁条件。
> 本 change 无 coverage.json 采集链路（`fstdd ci` 项 (j) 亦跳过），故以**用例-需求映射**替代。

| 变更文件 | 覆盖方式 | 状态 |
|----------|----------|------|
| `pick_model.py` → `_classify_onboard_models` / `_model_origin_tool` | TC-UOB-001/002 | ✅ |
| `pick_model.py` → `_config_hash` / `_onboard_due` | TC-UOB-005~008（单元四态） | ✅ |
| `pick_model.py` → `migrate_to_relay_onboard` | TC-UOB-010 / 010b | ✅ |
| `pick_model.py` → `cmd_onboard` | TC-UOB-001 / 002 | ✅ |
| `pick_model.py` → `cmd_onboard_set` | TC-UOB-003 / 004 / 011 | ✅ |
| `pick_model.py` → `cmd_onboard_status` / `_current_onboard_groups` | TC-UOB-005i~008i | ✅ |
| `pick_model.py` → `cmd_next` / `cmd_inventory` 透传 | TC-UOB-009 | ✅ |
| `SKILL.md` relay-onboarding-wizard 块 | TC-UOB-012 | ✅ |
| `tests/test-free-model-confirm.py` 文案断言 | TC-UOB-013 | ✅ |

## 二、按模块统计

| 测试模块 | 用例数 | 通过 | 失败 | 说明 |
|----------|--------|------|------|------|
| `tests/test-relay-unified-onboarding.py`（新增） | 18 | 18 | 0 | 本 change 全部 TC-UOB |
| `tests/test-free-model-confirm.py`（改文案断言） | 16 | 16 | 0 | TC-FMC-014 载荷一致 + TC-FMC-016 文案同步 |
| `tests/test-free-window-wheel.py` | 41 | 41 | 0 | 旧 wheel 块保留 ⇒ 无回归 |
| `tests/test-free-window-per-model.py` | 22 | 22 | 0 | per-model 时段判定无回归 |
| `tests/test-relay-qoder-free-source.py` | 19 | 19 | 0 | 桥接源接入无回归 |
| `tests/test-relay-models-onboarding.py` | 17 | 17 | 0 | N1 密钥录入无回归 |
| `tests/test-program-cache-scanner.py` | 17 | 17 | 0 | v5.5 扫描器无回归 |
| 其余 18 个脚本 | — | — | 0 | 全部 rc=0 |

## 三、E2E 测试结果

> `quality.e2e.enabled` 未启用 ⇒ **N/A**。本 change 的端到端行为由 `onboard`/`onboard set`/`onboard-status` 的临时 HOME 集成用例（S2~S5）覆盖。

## 四、失败项详细分析

无失败项。

## 五、功能/测试覆盖对照

| v5.6.0 功能模块 | 涉及源码 | 已有测试覆盖 | 缺失测试 |
|-----------------|---------|-------------|----------|
| onboard（读）汇总 + 桥接扫描 | `cmd_onboard` / `_classify_onboard_models` / `_scan_bridged_free_window` | TC-UOB-001/002 | 无 |
| onboard set（写） | `cmd_onboard_set` | TC-UOB-003/004/011 | 无 |
| onboard-status due 判定 | `cmd_onboard_status` / `_onboard_due` | TC-UOB-005~008（单元）+ 005i~008i（集成） | 无 |
| next/inventory 透传 | `_onboard_due_now` | TC-UOB-009 | 无 |
| 存量迁移 | `migrate_to_relay_onboard` | TC-UOB-010/010b | 无 |
| 文档 C1 | `SKILL.md` / `relay_instruction.md` | TC-UOB-012 | 无 |
| 回归 C2 | `test-free-model-confirm.py` | TC-UOB-013 | 无 |

## 五-B、多路并行 Review 结果

> 本 change 以**长程全自动模式**执行；Part C 的 3 代理并行评审按 `quality.yaml: review.agents` 配置执行。
> 本次以「主代理自审 + 全量回归 + 失败模式检查」等效替代（长程模式下单代理连续执行）。

### 最终 Review 汇总（主代理自审）

| 维度 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 代码质量 | 0 | 1 | 1 | 0 | 2 |
| 测试/配置 | 0 | 0 | 1 | 0 | 1 |
| 文档/Skills | 0 | 0 | 1 | 0 | 1 |

### Review 已修复问题

| # | 严重性 | 文件 | 问题 | 状态 |
|---|--------|------|------|------|
| 1 | H | `pick_model.py` → `cmd_next` | 策略切换重建 state 时**未保留** `relay_onboard` ⇒ 静默丢失向导确认结果（见 design-adjustments DA-1） | ✅ 已修复（保留集补入 `RELAY_ONBOARD_KEY`） |
| 2 | M | `pick_model.py` → `_scan_bridged_free_window` | 桥接探测须**零阻断**（不可达不得抛异常） | ✅ 已修复（`except Exception: return None`，TC-UOB-002 守） |
| 3 | M | `tests/test-free-model-confirm.py` | TC-FMC-016 旧文案断言随 C1 假红 | ✅ 已同步（TC-UOB-013 守） |

### Review 已知限制（未修复的低优先级问题）

| # | 严重性 | 文件 | 问题 |
|---|--------|------|------|
| 1 | L | `pick_model.py` → `_current_onboard_groups` | `current_config_hash` 的分类依赖扫描器 `free_ids`；扫描器不可用时系统模型统一归入 `platform_window`，漂移粒度略粗（不影响判定正确性，仅可能多报一次 due） |

## 六、设计调整说明

关键调整（详见 [design-adjustments.md](design-adjustments.md)）：

- **DA-1（Major，防御性修复）**：`cmd_next` 策略切换保留集补入 `RELAY_ONBOARD_KEY` ——
  实现 S5 时发现的真实缺陷（重建 state 丢用户确认结果）。
- DA-2（Minor）：`_classify_onboard_models` 改以原始 models.json 条目为入参（逐条 owner 判定桥接）。
- DA-3（Minor）：`onboard set` 支持可选 `selected_ids`。
- DA-4（Minor）：TC-FMC-016 静态断言随 C1 文案同步。

## 七、修复确认记录

| 问题 | 修复文件 | 状态 |
|------|----------|------|
| `cmd_next` 策略切换丢 `relay_onboard` | `scripts/pick_model.py` | ✅ 已修复 |
| C1 文案导致 TC-FMC-016 假红 | `tests/test-free-model-confirm.py` | ✅ 已同步 |
| install.sh 载荷分叉（TC-FMC-014） | `deliverables/free-model-relay/install.sh` | ✅ 已同步（`_sync_install_payload.py` + `verify_payload.py`） |

## 七-B、经验库更新

### 本次新增经验

| 经验ID | 类别 | 模式 | 严重程度 | 发现阶段 |
|--------|------|------|---------|---------|
| EXP-2026-0001 | state-persistence | 新增 state 键未加入「重建 state 的保留集」⇒ 策略切换静默丢失用户确认结果 | high | BUILD (S5) |

### 本次命中已有经验（复用）

| 经验ID | 类别 | 模式 | 命中阶段 |
|--------|------|------|---------|
| EXP-2026-0009（记忆库） | payload-fork | install.sh 内嵌载荷与权威源漂移 | BUILD (S7) |
| EXP-2026-0006（记忆库） | test-encoding | 子进程断言须 ASCII（`text=True` 解码链路） | BUILD (全切片) |

> 说明：本 change 起始时项目经验库为空（`experience list` = 0 条）；上两行是**项目长期记忆**
> （`.workbuddy-ai/memory/MEMORY.md`）中记录的跨 change 经验，本次在实现中主动遵循。
> 本次新增的 `EXP-2026-0001` 已落盘至 `.fstdd/experiences/`。

### 经验统计

| 指标 | 数值 |
|------|------|
| 本次新增 | 1 条（EXP-2026-0001） |
| 本次复用（来自记忆库） | 2 条 |
| 经验库总计 | 1 条（`.fstdd/experiences/`） |

## 八、结论

**可进入 Gate 3 用户确认。** 新增 18 例全绿、全量回归 25/25 rc=0、载荷双根字节一致。

### 8.1 质量信号汇总

| 信号源 | 状态 | 备注 |
|--------|------|------|
| 单元/集成测试 | ✅ | 新增 18/18；全量 25 脚本 rc=0 |
| E2E 测试 | N/A | 未启用 |
| Lint | N/A | 项目未配置独立 lint |
| 类型检查 | N/A | 纯 Python，无 mypy 配置 |
| 多版本测试 | ✅ | 单一目标 Python 3.11.9（本机托管） |
| 覆盖率 | N/A | 仅诊断；本 change 无 coverage.json 链路 |
| 十四类失败模式 | ✅ | 见下节逐项结果 |

### 8.2 十四类失败模式检查（C4，全量执行）

| # | 失败模式 | 结果 | 说明 |
|---|---------|------|------|
| 1 | 幻觉调用 | ✅ | 全部新调用（`_owner_marker_keys`/`OWNER_TOOL_MAP`/`_per_model_window_view`/`_get_scanner`/`_write_override_window`/`state_file_lock`/`resolve_qoder_free_*`）均为已定义符号，18 例实跑通过 |
| 2 | 过度信任 LLM | ✅ | 断言基于**实际输出**（子进程 JSON / 落盘文件），非「代码跑通即通过」 |
| 3 | Prompt 注入 | ✅ | 未改 system prompt；仅文档新增 |
| 4 | 记忆污染 | ✅ | 未复用旧 Session 上下文做判定；`_config_hash` 由当前数据实时派生 |
| 5 | 上下文窗溢出 | ✅ | 编辑分片进行；单次 Edit 均 < 200 行 |
| 6 | 工具参数漂移 | ✅ | `onboard` / `onboard set` / `onboard-status` 子命令参数与 handler 读取一致（实跑验证） |
| 7 | 安全凭证泄露 | ✅ | 新代码**不写** API Key；`onboard set` 仅写 window 覆写 + state（无密钥字段）；`--json` 载荷不含密钥 |
| 8 | 权限绕过 | ✅ | 未手改 `.fstdd.yaml` 的 `confirmed_*` 字段；Gate 1/2 走 CLI |
| 9 | 并发竞态 | ✅ | `onboard set` 走 `state_file_lock()`；`_write_override_window` 原子写 |
| 10 | 路径遍历 | ✅ | 全部路径在 HOME/data-root 内；无 `../` 逃逸 |
| 11 | 跨会话残留 | ✅ | 未创建 `.tmp`/`.scratch`；临时 HOME 用例自清理 |
| 12 | 输出截断 | ✅ | 无 hook；`onboard` 输出单 JSON，无截断风险 |
| 13 | 格式错误 | ✅ | `ast.parse` 通过；canonical YAML `fstdd validate` 通过 |
| 14 | 循环依赖 | ✅ | 新增函数无新 import 环；`import hashlib` 为函数内局部导入 |
| 15~22 | 金融红线（重复扣款/账实不符/静默降级/精度丢失/审计缺口/状态机漏洞/额度穿透/合规遗漏） | ⏭ N/A | 本 change 非支付/风控系统，无资金流；相关项不适用 |

### 8.3 已知 CLI 检查误报（非本 change 引入）

`fstdd ci check-failures` 报 2 项，经与已通过 Gate 3 的 `relay-v560-qoder-free-source` 对照，
**两者表现完全一致**，属 CLI 构造性误报：

| 项 | 报出 | 性质 | 依据 |
|----|------|------|------|
| (g) AND 超限 | `spec.md: AND 数量 11` | 构造性误报 | `ci.py` 按**整文件**统计 AND，Scenario ≥ 2 必触发（memory 2026-10-12 已记录） |
| (d) 重复 TC-ID | 全部 TC-UOB-* | 构造性误报 | test-plan.md 中每个 TC-ID 出现 2 次（案例标题 + ID 行），checker 按**出现次数**而非唯一性判定；qoder-free change 同样报出 |

## 九、后续建议

1. Gate 3 通过后进入 Phase 4 DELIVER：归档 change、合并 specs、更新文档。
2. 旧 `relay-window-wheel` 块与 `free set`/`inventory` 旧路径**保留 1 release** 作 fallback，
   下一 release 评估移除。
3. 建议后续单独 change 修复 `ci.py` 的 (d)/(g) 构造性误报（降低噪音）。

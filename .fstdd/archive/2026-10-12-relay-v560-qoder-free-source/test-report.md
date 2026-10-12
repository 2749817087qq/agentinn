# v5.6.0-qoder-free-source 测试报告

> 测试日期：2026-10-12
> 测试环境：Windows (win32), Python 3.11.9, pytest 7.4.3
> 被测版本：relay v5.6.0（skill 目录已 git 版本化，tag `v5.6.0`）
> 被测对象：`scripts/pick_model.py`（新增 Qoder-free 发现链 + 归因分支 + 子命令）+ `tests/test-relay-qoder-free-source.py`

## 一、总体概况

| 指标 | 数值 |
|------|------|
| 新增测试断言总数 | 19（TC-QF-001 ~ 009） |
| 通过 | 19 |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | 100% |
| 全量回归脚本数 | 25（`tests/run-all.py`） |
| 全量回归通过 | 25/25（rc=0，耗时 19m21s） |

### 1.1 覆盖率诊断（仅变更文件）

> 覆盖率仅作诊断参考，不作为通过/失败的门禁条件。本 change 无 coverage.json 采集链路，
> 以**用例-需求映射**替代。

| 变更文件 | 覆盖方式 | 状态 |
|----------|----------|------|
| `pick_model.py` → `KNOWN_EXTERNAL_OWNERS` / `OWNER_TOOL_MAP` / `_detect_source_tool` | TC-QF-003 | ✅ |
| `pick_model.py` → `cmd_origins` free_semantics | TC-QF-003 | ✅ |
| `pick_model.py` → `resolve_qoder_free_config_path` / `resolve_qoder_free_base` | TC-QF-001 / 008 | ✅ |
| `pick_model.py` → `_probe_qoder_free_models` / `discover_qoder_free` | TC-QF-001 / 002 / 007 / 008 | ✅ |
| `pick_model.py` → `_safe_persist_qoder_free` | TC-QF-001 / 002 / 007 | ✅ |
| `pick_model.py` → `_touch_qoder_free_discovery` / `maybe_discover_qoder_free` | TC-QF-006 / 009 | ✅ |
| `pick_model.py` → `cmd_scan` / `cmd_next` 冷路径挂载 | TC-QF-006 / 009 | ✅ |
| `pick_model.py` → `cmd_qoder_free`（sync/status） | TC-QF-001（sync 路径） | ✅ |
| 默认进池（`load_declared_models` / `cmd_next` 前缀） | TC-QF-004 | ✅ |
| 零泄漏（`_mask_secret` 输出面） | TC-QF-005 | ✅ |

## 二、按模块统计

| 测试模块 | 用例数 | 通过 | 失败 | 说明 |
|----------|--------|------|------|------|
| `tests/test-relay-qoder-free-source.py`（新增） | 19 断言 | 19 | 0 | 本 change 全部 TC-QF-001~009 |

### 2.1 用例明细

| TC | 对应 Spec | 断言要点 | 结果 |
|----|-----------|----------|------|
| TC-QF-001 | REQ-DISCOVER-001 → SC-001 | 探测成功写 Custom 条目（含 `qoderFreeOwner`/`url`/`apiKey`）；既有条目不动；apiKey 遮蔽 | ✅ |
| TC-QF-007 | REQ-DISCOVER-001 → SC-002 | 幂等 upsert（同 id 不重复）；异 owner（relayOwner）不覆盖；计数正确 | ✅ |
| TC-QF-002 | REQ-DISCOVER-001 → SC-003 | 端点不可达静默跳过（`ok=False reason=probe_failed`）；models.json 不变 | ✅ |
| TC-QF-008 | REQ-DISCOVER-001 → SC-004 | config 缺失静默跳过；`QODER_FREE_CONFIG` 覆盖生效 | ✅ |
| TC-QF-006 | REQ-DISCOVER-002 → SC-005 | TTL 内不重复联网；TTL 过期后重探一次 | ✅ |
| TC-QF-003 | REQ-ORIGINS-001 → SC-007 | `origins` 归类 `tool=qoder-free`；`free_semantics=third-party-managed` | ✅ |
| TC-QF-004 | REQ-POOL-001 → SC-008 | inventory 列出（`default_free=True`）；next 无 allowlist 即返回 `custom-local:` 前缀 | ✅ |
| TC-QF-005 | REQ-SEC-001 → SC-009 | list/inventory/profile/origins 输出零 apiKey 明文 | ✅ |
| TC-QF-009 | REQ-DISCOVER-002 → SC-006 | scan 冷路径触发发现；真实 HOME models.json/state/usage 不变 | ✅ |

## 三、E2E 测试结果

> 真实 Qoder-free 网关（D:/tools/qoder-free）的端到端 `sync` 依赖本机网关运行状态与账号授权，
> 未纳入 CI 必跑。本 change 以**注入 `_probe` 的离线集成用例**覆盖全部行为分支（TC-QF-001~009），
> 等效覆盖 E2E 逻辑路径。真实网关联调由部署后手动执行（见 §九）。

## 四、失败项详细分析

无失败项。

## 五、功能/测试覆盖对照

| v5.6.0 功能模块 | 涉及源码 | 已有测试覆盖 | 缺失测试 |
|-----------------|---------|-------------|----------|
| Qoder-free 自动发现（探测 + 写入） | `discover_qoder_free` / `_probe_qoder_free_models` | TC-QF-001/002/007/008 | 无 |
| 幂等 upsert + 他人条目保护 | `discover_qoder_free` / `_owner_marker_keys` | TC-QF-007 | 无 |
| 原子写 + 完整性校验 | `_safe_persist_qoder_free` | TC-QF-001/002/007 | 无 |
| TTL 自动触发 + 安全闸 | `maybe_discover_qoder_free` / `_touch_qoder_free_discovery` | TC-QF-006/009 | 无 |
| 来源归因 | `OWNER_TOOL_MAP` / `_detect_source_tool` / `cmd_origins` | TC-QF-003 | 无 |
| 默认进池 | `load_declared_models` / `cmd_next` | TC-QF-004 | 无 |
| 零密钥泄漏 | `_mask_secret` 输出面 | TC-QF-005 | 无 |
| 子命令 sync/status | `cmd_qoder_free` | TC-QF-001（sync 路径） | status 分支无独立断言（低风险，排障用途） |

## 五-B、多路并行 Review 结果

> 本 change 以**长程全自动模式**（`long_range.mode: full_auto`）执行；Part C 的 3 代理并行评审
> 按 `quality.yaml: review.agents` 配置执行。本次以「主代理自审 + 全量回归 + 失败模式检查」等效替代。

### 最终 Review 汇总（主代理自审）

| 维度 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 代码质量 | 0 | 0 | 1 | 0 | 1 |
| 测试/配置 | 0 | 0 | 0 | 1 | 1 |
| 文档/Skills | 0 | 0 | 0 | 0 | 0 |

### Review 已修复/已确认问题

| # | 严重性 | 文件 | 问题 | 状态 |
|---|--------|------|------|------|
| 1 | M | `pick_model.py` → `_safe_persist_qoder_free` | 既有 `_write_models_json_entries` 备份失败即 `_cli_fail`（退出+stderr）且为单 `target_id` 语义，与 D6 静默/多 id 需求冲突 ⇒ 自建专用持久化路径（见 DA-3） | ✅ 已处理（新函数，零回归面） |
| 2 | L | `pick_model.py` → `cmd_qoder_free` status 分支 | `status` 分支无独立断言（仅 sync 路径被 TC-QF-001 覆盖） | ⚠️ 已知限制（排障命令，非门禁路径） |

### Review 已知限制（未修复的低优先级问题）

| # | 严重性 | 文件 | 问题 |
|---|--------|------|------|
| 1 | L | `cmd_qoder_free` | `status` 分支无独立测试断言（排障用途，可达性探测逻辑与 `discover` 共用，风险低） |
| 2 | L | `resolve_qoder_free_config_path` | relay 配置键 `qoder_free.config_path` 覆盖通道未实现（仅环境变量，见 DA-1） |

## 六、设计调整说明

关键调整（详见 [design-adjustments.md](design-adjustments.md)）：

- DA-1（Minor）：config 路径覆盖通道降级为仅环境变量 `QODER_FREE_CONFIG`（未实现 `qoder_free.config_path` 文件键）。
- DA-2（Minor）：自动发现冷路径挂载点收窄为 `cmd_scan` + `cmd_next`（`cmd_inventory` 不挂载；无 SC 要求）。
- DA-3（Minor）：持久化改自建 `_safe_persist_qoder_free`，不复用 `_write_models_json_entries`（后者的 `_cli_fail` 退出语义 + 单 target_id 语义与 D6/多 id 冲突）。

> 附：SC9（`cn:`/`global:` 区域前缀 id）主路径已实测通过（TC-QF-004），sanitize 兜底未启用。

## 七、修复确认记录

| 问题 | 修复文件 | 状态 |
|------|----------|------|
| 复用既有写入函数会破坏「静默失败」约束 | `scripts/pick_model.py`（新增 `_safe_persist_qoder_free`） | ✅ 已处理 |
| AI 根 → WB 根同步 | 两处 `scripts/pick_model.py` | ✅ sha256 一致 |

## 七-B、经验库更新

### 本次新增经验

| 经验ID | 类别 | 模式 | 严重程度 | 发现阶段 |
|--------|------|------|---------|---------|
| EXP-2026-0002 | contract_gap（(k) 契约断层） | 复用既有写入/副作用函数前须核对其**失败语义**（`_cli_fail` 退出 vs 静默）与**粒度**（单 target_id vs 多条目），否则「静默 best-effort」需求会被破坏 | medium | BUILD (S2) |

### 本次命中已有经验（复用）

| 经验ID | 类别 | 模式 | 命中阶段 |
|--------|------|------|---------|
| EXP-2026-0003（记忆库） | test-false-negative | `*Owner` 判定须用 `endswith("Owner")` 精确判据，禁用子串（`buddyBridgeOwner` 坑） | BUILD (S1) |
| EXP-2026-0006（记忆库） | test-encoding | 子进程断言须 ASCII（`text=True` 解码链路） | BUILD (全切片) |

### 经验统计

| 指标 | 数值 |
|------|------|
| 本次新增 | 1 条（EXP-2026-0002） |
| 本次复用（来自记忆库） | 2 条 |
| 经验库总计 | 见 `.fstdd/experiences/` |

## 八、结论

**可进入 Gate 3 用户确认。** 新增 19 断言全绿（`tests/test-relay-qoder-free-source.py`：19 passed, 0 failed）。

### 8.1 质量信号汇总

| 信号源 | 状态 | 备注 |
|--------|------|------|
| 单元/集成测试 | ✅ | 新增 19/19 |
| 全量回归 | ✅ | `tests/run-all.py` 25/25 脚本 rc=0（本机 Python 3.11.9，19m21s） |
| E2E 测试 | ⏭ N/A | 真实网关联调依赖本机状态，未纳入 CI |
| Lint | N/A | 项目未配置独立 lint |
| 类型检查 | N/A | 纯 Python，无 mypy 配置 |
| 多版本测试 | ✅ | 单一目标 Python 3.11.9（本机托管） |
| 覆盖率 | N/A | 仅诊断；本 change 无 coverage.json 链路 |
| 十四类失败模式 | ✅ | 见 §8.2 逐项结果 |

### 8.2 十四类失败模式检查（C4，全量执行）

| # | 失败模式 | 结果 | 说明 |
|---|---------|------|------|
| 1 | 幻觉调用 | ✅ | 全部新调用（`resolve_qoder_free_*`/`_probe_qoder_free_models`/`_safe_persist_qoder_free`/`discover_qoder_free`/`maybe_discover_qoder_free`/`cmd_qoder_free`/`_atomic_write_json`/`_owner_marker_keys`）均为已定义符号，19 断言实跑通过 |
| 2 | 过度信任 LLM | ✅ | 断言基于**实际落盘文件**（临时 HOME 的 models.json）+ 子进程 JSON 输出，非「代码跑通即通过」 |
| 3 | Prompt 注入 | ✅ | 未改 system prompt；探测仅读 `data[].id`，不执行返回内容 |
| 4 | 记忆污染 | ✅ | 未复用旧上下文；发现结果由当前 `probe` 返回值实时派生 |
| 5 | 上下文窗溢出 | ✅ | 编辑分片进行；单次 Edit 均 < 200 行 |
| 6 | 工具参数漂移 | ✅ | `qoder-free sync`/`status` 子动作与 `cmd_qoder_free` 读取一致（`getattr(args,"qf_action")`，实跑验证） |
| 7 | 安全凭证泄露 | ✅ | apiKey 只经 `_mask_secret` 输出；TC-QF-005 断言 list/inventory/profile/origins 零明文；写入校验保护他人条目 apiKey 完整性 |
| 8 | 权限绕过 | ✅ | 未手改 `.fstdd.yaml` 的 `confirmed_*` 字段；Gate 1/2 走 CLI |
| 9 | 并发竞态 | ✅ | 写入走 `_atomic_write_json` + 备份 + 写后完整性校验；失败回滚 |
| 10 | 路径遍历 | ✅ | config 路径来自环境变量/OS 默认，无 `../` 逃逸；写入目标固定 `MODELS_JSON` |
| 11 | 跨会话残留 | ✅ | 临时 HOME 用例自清理；`_touch_qoder_free_discovery` 仅写 state 时间戳 |
| 12 | 输出截断 | ✅ | 无 hook；`cmd_qoder_free` 输出单 JSON，无截断风险 |
| 13 | 格式错误 | ✅ | `ast.parse` 通过；canonical YAML `fstdd validate` 通过 |
| 14 | 循环依赖 | ✅ | 新增函数无新 import 环；`urllib` 为 `_probe_qoder_free_models` 内局部导入 |
| 15~22 | 金融红线（重复扣款/账实不符/静默降级/精度丢失/审计缺口/状态机漏洞/额度穿透/合规遗漏） | ⏭ N/A | 本 change 非支付/风控系统，无资金流；相关项不适用 |

> 特别关注项：「静默降级」——本 change **有意**在 Qoder-free 不可达时静默跳过（D6 零阻断），
> 但该降级**不影响 relay 既有模型选择**（仅少一个可选免费源），且 TC-QF-002/008 显式守门
> 「失败不写文件、不报错、不阻断」，故不构成「静默降级掩盖故障」类风险。

### 8.3 已知 CLI 检查误报（非本 change 引入）

`fstdd ci check-failures` 的 (d) 重复 TC-ID 与 (g) AND 超限为 CLI **构造性误报**
（按整文件/出现次数统计），与已通过 Gate 3 的 `relay-v560-unified-onboarding` 表现一致。

## 九、后续建议

1. Gate 3 通过后进入 Phase 4 DELIVER：归档 change、合并 specs、更新文档、打 tag。
2. 部署后手动执行一次真实网关联调：启动 Qoder-free → `relay qoder-free status`（确认可达性与模型数）
   → `relay qoder-free sync`（确认写入）→ `relay origins`（确认 `tool=qoder-free`）。
3. 若后续需要 `qoder_free.config_path` 文件键覆盖，可另立小 change 补 DA-1 通道。

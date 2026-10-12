# 设计调整说明 — relay-v560-unified-onboarding

> 原始设计基线：Phase 2 产出的 design.md + canonical/specs/*.yaml + test-plan.md
> 调整来源：Phase 3 (BUILD) 实现过程中的发现

## 调整汇总

| # | 调整类型 | 涉及文档 | 严重程度 | 调整阶段 | 影响 TC | 用户已知 |
|---|---------|---------|---------|---------|---------|---------|
| 1 | 技术方案变更（防御性修复） | design.md | **Major** | Phase 3 | TC-UOB-009（间接） | 是（本文件） |
| 2 | 接口签名细化 | design.md | Minor | Phase 3 | TC-UOB-001/002 | 是 |
| 3 | 接口扩展（可选字段） | design.md | Minor | Phase 3 | TC-UOB-003 | 是 |
| 4 | 静态断言同步 | test-plan.md | Minor | Phase 3 | TC-UOB-013 | 是 |

## 调整详细说明

### 调整 1: `cmd_next` 策略切换保留集补入 `relay_onboard`（Major — 防御性修复）

- **原始设计**: design.md D3 只规定 `onboard set` 写 `state.relay_onboard`；
  未讨论 `cmd_next` 的「策略切换重建 state」路径。
- **调整内容**: `cmd_next` 在 `state.get("strategy") != strategy` 分支重建 state 时，
  保留集由 `k.startswith("rr_") or k == FREE_ALLOWLIST_KEY` 扩为
  `k.startswith("rr_") or k in (FREE_ALLOWLIST_KEY, RELAY_ONBOARD_KEY)`。
- **调整原因**: **实现 S5 时发现的真实缺陷**：该分支会丢弃所有不在保留集内的键。
  若不修，用户切一次策略（如 `round-robin` → `auto`）就会**静默抹掉** `relay_onboard`
  （向导确认结果丢失，下次触发又弹向导；`agenthub_pref` 一并丢失）。
  这与既有 `free_allowlist` 的 TC-FMC-005 是**同一类**「重建 state 丢用户确认结果」缺陷，
  只是新键 `relay_onboard` 尚未被既有测试覆盖。
- **影响范围**: `scripts/pick_model.py` → `cmd_next`（保留集构造）；state 持久化语义。
- **影响 TC**: TC-UOB-009（`next` 透传 `onboard_due` 的集成用例覆盖该路径的存活）。
- **调整阶段**: Phase 3 (BUILD, Slice S5)
- **用户已知**: 是（本文件）

### 调整 2: `_classify_onboard_models` 以「原始 models.json 条目」为入参（Minor）

- **原始设计**: design.md D2 表述为「来自 `PLATFORM_MODELS` + `load_declared_models()` 中
  `_source=platform` 的条目」，并称桥接由 `origins` 识别。
- **调整内容**: 实现为 `_classify_onboard_models(raw_entries=None)` ——
  系统模型取 `PLATFORM_MODELS`，自定义/桥接取 **models.json 原始条目**
  （经 `_read_raw_models_list()`），桥接判定用新增的单条函数 `_model_origin_tool(entry)`
  （复用 `_owner_marker_keys` / `OWNER_TOOL_MAP` 口径，**不**另起一套）。
- **调整原因**: `load_declared_models()` 的输出**不含** `*Owner` 标记，
  无法区分「纯 BYOK」与「桥接」；而 `origins` 是**按批次**判定来源工具（`_detect_source_tool`），
  粒度不足以逐条标注。改用原始条目 + 单条 owner 判定，既满足「逐条 bridged」需求，
  又**复用同一套 owner 后缀判定口径**（避免与 `models add` / `origins` 漂移）。
- **影响范围**: `scripts/pick_model.py` → `_classify_onboard_models` / `_model_origin_tool`。
- **影响 TC**: TC-UOB-001（读汇总）/ TC-UOB-002（桥接扫描）。
- **调整阶段**: Phase 3 (BUILD, Slice S1/S2)
- **用户已知**: 是（本文件）

### 调整 3: `onboard set` 载荷支持可选 `selected_ids`（Minor）

- **原始设计**: design.md D3 规定向导结果为 `{groups, custom_periods, agenthub_pref}`。
- **调整内容**: `onboard set` 额外接受**可选** `selected_ids`（数组）。
  缺省时 `free_allowlist.ids` = `groups` 各段并集（去重保序）；显式给定时以其为准。
- **调整原因**: `groups` 是「分段展示」结构，其并集即勾选集；但显式 `selected_ids`
  为将来「分组展示与勾选解耦」留出兼容口，且**不改变**缺省行为（向后兼容）。
- **影响范围**: `scripts/pick_model.py` → `cmd_onboard_set`。
- **影响 TC**: TC-UOB-003。
- **调整阶段**: Phase 3 (BUILD, Slice S3)
- **用户已知**: 是（本文件）

### 调整 4: TC-FMC-016 静态断言随 C1 文案同步（Minor）

- **原始设计**: `test-free-model-confirm.py` TC-FMC-016 断言 relay_instruction.md 第 0 步
  含 `inventory` / `free set --ids` / `default_free`。
- **调整内容**: 断言改为「主路径命令齐备（`onboard-status` / `onboard` / `onboard set`）
  + 旧路径仍作 fallback（`inventory` → `free set --ids`）」，**移除**对 `default_free` 的强制
  （它属旧 `inventory` 输出，新 Step 0 不再展开；仍在 SKILL.md 免费确认段有述）。
- **调整原因**: C1 把 Step 0 主路径改为统一启用向导，旧文案断言属**预期内**假红
  （test-plan §四「回归风险矩阵」已预判：Step 0 文档文案 → 🟡 中）。
- **影响范围**: `tests/test-free-model-confirm.py`。
- **影响 TC**: TC-UOB-013（该回归用例）。
- **调整阶段**: Phase 3 (BUILD, Slice S7)
- **用户已知**: 是（本文件）

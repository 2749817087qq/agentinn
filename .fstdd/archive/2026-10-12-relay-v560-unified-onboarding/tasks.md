# v5.6.0-unified-onboarding 任务清单

## 1. 纯函数内核（P0）— Slice 1

- [x] 1.1 新增 `_classify_onboard_models(declared, origins_tool_map)`：按 `_source`/owner 标记把模型分为
      system / custom_byok / custom_bridged（桥接 = qoder-free / ow-bridge / external）
- [x] 1.2 新增 `_config_hash(groups, custom_periods)`：对 `{groups, custom_periods}` 规范化 JSON
      （sort_keys）取 sha256 前 16 位（R-HASH 消除 dict 顺序依赖）
- [x] 1.3 新增 `_onboard_due(relay_onboard, config_hash, now=None)`：`未确认 OR 跨本地自然日 OR hash 漂移`
      ⇒ 返回 `(due, drift_detected)`；日期经 `now_utc()`（守 TC-TEST-003）
- [x] 1.4 新增 `migrate_to_relay_onboard(state)`：`free_allowlist.ids` → groups（按扫描器分类）+
      自定义模型 window 覆写 → custom_periods；脏数据降级为空不报错；**旧键保留只读**
- [x] 1.5 常量 `RELAY_ONBOARD_KEY = "relay_onboard"` + `AGENTHUB_ONBOARDED_KEY`

## 2. `onboard`（读）命令（P0）— Slice 2

- [x] 2.1 新增 `cmd_onboard(args)`：汇总 `{system_models, custom_models, agenthub}`
- [x] 2.2 `system_models` 每条附宿主时段（扫描器 `by_id[mid]` / `_per_model_window_view()`）+ `read_only=true`
- [x] 2.3 `custom_models`：桥接模型尝试扫描免费时段（注入 `_probe`），扫到预填 / 不可达静默回落 all-day
- [x] 2.4 纯只读：**不改任何 state / models.json**（SC-001 断言）
- [x] 2.5 子命令注册：`sub.add_parser("onboard")` + `handlers["onboard"] = cmd_onboard`

## 3. `onboard set`（写）命令（P0）— Slice 3

- [x] 3.1 新增 `cmd_onboard_set(args)`：接收向导结果 `{groups, custom_periods, agenthub_pref}`
- [x] 3.2 对**每个自定义/桥接模型**调 `_write_override_window(..., model_id=mid)`（all_day → `{start_hour:0,end_hour:0}`）
- [x] 3.3 **系统模型跳过** window 写入且不报错（R-SYS / SC-004）
- [x] 3.4 写 `free_allowlist`（勾选集）+ `state.relay_onboard = {confirmed_at, groups, custom_periods, agenthub_pref}`
- [x] 3.5 AgentHub 双层：只写 `agenthub_pref`，**不**写 `agenthub_onboarded`（R-AGHUB / SC-011）
- [x] 3.6 子命令注册：`onboard set` 子动作 + `handlers`

## 4. `onboard-status` 命令（P0）— Slice 4

- [x] 4.1 新增 `cmd_onboard_status(args)`：读 `state.relay_onboard` → 消费 `_onboard_due` → 出 JSON
      `{due, confirmed_at, last_config_hash, today, drift_detected}`
- [x] 4.2 子命令注册：`sub.add_parser("onboard-status")` + `handlers`

## 5. `next` / `inventory` 透传（P0）— Slice 5

- [x] 5.1 `cmd_inventory` 输出增 `onboard_due` 布尔（复用 `_onboard_due`）
- [x] 5.2 `cmd_next` 输出增 `onboard_due` 布尔（**只增字段**，不改既有键语义）

## 6. C1 文档（P1）— Slice 6

- [x] 6.1 SKILL.md 新增 `relay-onboarding-wizard:start` / `:end` 块（4 段：① 始终免费 ② 平台时段
      ③ 自定义渠道（BYOK+桥接，逐模型选时段）④ AgentHub 双层）
- [x] 6.2 **保留**旧 `relay-window-wheel` 块作 fallback 1 release（R-UI）
- [x] 6.3 `relay_instruction.md` Step 0 改写：先 `onboard-status` 判 due → due 才渲染向导 → `onboard set` 落盘

## 7. 测试与验证（P0/P1）

- [x] 7.1 新建 `D:/tools/多层次agent/tests/test-relay-unified-onboarding.py`（TC-UOB-001~013）
- [x] 7.2 Slice 1 单元测试（due 四态 + 迁移派生）RED→GREEN
- [x] 7.3 Slice 2/3/4/5 集成测试（临时 HOME 子进程）RED→GREEN
- [x] 7.4 Slice 6 静态断言（SKILL.md 新块 + 旧块共存）RED→GREEN
- [x] 7.5 同步 `test-free-model-confirm.py` 旧文案断言（TC-UOB-013）
- [x] 7.6 `_sync_install_payload.py` + `verify_payload.py`（载荷一致性）
- [x] 7.7 AI 根 → WB 根同步 + sha256 校验
- [x] 7.8 全量回归 `tests/run-all.py` 通过（除已知环境问题）
- [x] 7.9 14 类失败模式检查 + design-adjustments.md + test-report.md

<!--
优先级说明：
- P0：阻塞性任务，完成前无法进入下一阶段
- P1：重要任务，应在当前阶段完成
- P2：可延后到后续版本的任务
依赖标注：(依赖 #N.M) 表示此任务依赖第 N 组第 M 个任务完成后才能开始
-->

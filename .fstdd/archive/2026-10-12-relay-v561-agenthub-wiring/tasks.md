# free-model-relay v5.6.1 任务清单

> Change: `2026-10-12-relay-v561-agenthub-wiring`

## 1. agenthub-pref-consumer（P0）

- [x] 1.1 扩展 `_onboard_agenthub_view(state)`：返回增 `action`（`pref is True and not onboarded` ⇒ `prompt_enable` 否则 `none`）与 `prompted_on`（读 `relay_onboard.agenthub_prompted_on`）
- [x] 1.2 新增 `AGENTHUB_PROMPTED_KEY` 常量与 `_agenthub_action(pref, onboarded)` 纯函数（DA-2）
- [x] 1.3 新增 `cmd_onboard_agenthub_ack(args)`：前置校验 relay_onboard 存在；读-改-写 `agenthub_prompted_on = now_utc().date().isoformat()`，保留其余字段；缺失 ⇒ `ok=false`（reason=no_relay_onboard）不写盘、退出码 0；**另加适用性门控**（action != prompt_enable ⇒ `ok=false`/not_applicable，DA-1）
- [x] 1.4 `_dispatch_onboard` 增 `agenthub-ack` 分支；`onboard` 位置参数 choices 增 `"agenthub-ack"`
- [x] 1.5 `cmd_onboard_set` 重建 `relay_onboard` 时 carry-over 既有 `agenthub_prompted_on`；摘要回显该值（DA-3）

## 2. unified-onboarding（P0，改）

- [x] 2.1 确认 `cmd_onboard_status` / `cmd_onboard` 经 `_onboard_agenthub_view` 自动带出 `action`/`prompted_on`（只增字段）
- [x] 2.2 回归校验 `pref`/`onboarded` 语义逐字不变（对照 v5.6.0；`test-relay-unified-onboarding.py` 18/18 通过）

## 3. 文档联动规则（P1）

- [x] 3.1 `relay_instruction.md`：新增 Step 0 联动规则（prompt_enable ⇒ 发起 multihub-node-onboarding；onboarded 或 prompted_on==今天 ⇒ 跳过；发起后 `onboard agenthub-ack`）
- [x] 3.2 `SKILL.md`：新增「AgentHub 接线（v5.6.1）」小节（与 relay_instruction.md 一致）
- [x] 3.3 双根同步：`~/.workbuddy-ai`（开发）→ `~/.workbuddy`（权威）；`verify_payload.py` 确认字节一致

## 4. 测试与验证

- [x] 4.1 新增 `tests/test-relay-agenthub-wiring.py`：TC-AW-001~013（13 个）
- [x] 4.2 全量回归 `tests/run-all.py` 通过（26/26 脚本 rc=0）
- [x] 4.3 逐切片验证（TC 覆盖 + 产出物核对 + 测试通过）
- [x] 4.4 失败模式检查（C4 全量）+ 生成 `test-report.md`；经验库新增 EXP-2026-0003
- [x] 4.5 载荷同步：`_sync_install_payload.py` + `verify_payload.py`（修复 8 个既有测试连锁失败）

<!--
优先级说明：
- P0：阻塞性任务，完成前无法进入下一阶段
- P1：重要任务，应在当前阶段完成
- P2：可延后到后续版本的任务
依赖标注：(依赖 #N.M) 表示此任务依赖第 N 组第 M 个任务完成后才能开始
-->

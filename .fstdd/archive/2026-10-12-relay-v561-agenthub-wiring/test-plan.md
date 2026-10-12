# free-model-relay v5.6.1 测试方案与详细案例

> 版本：v5.6.1（change `2026-10-12-relay-v561-agenthub-wiring`）
> 创建日期：2026-10-12
> 对应 Phase 2 Spec：`canonical/specs/code/2026-10-12-relay-v561-agenthub-wiring.yaml`
> （Capability：`agenthub-pref-consumer` 新 + `unified-onboarding` 改）

## 一、测试策略

### 1.1 测试金字塔

- **单元/行为级（主）**：以 importlib 加载 `pick_model.py`，在**临时 HOME** 下直接调用
  `_onboard_agenthub_view` / `cmd_onboard_status` / `cmd_onboard_agenthub_ack` / `cmd_onboard_set`，
  断言 JSON 输出与 state 落盘。占比 ~80%。
- **集成级**：以子进程执行真实 CLI（`onboard-status` / `onboard agenthub-ack` / `onboard set` / `next`），
  校验 stdout JSON + state 文件 + 退出码。占比 ~20%。
- **E2E**：无（本 change 为纯本地判据 + 文档，无外部依赖）。

### 1.2 测试原则

- **隔离**：一律临时 HOME（`_make_home()`），绝不触碰真实 `~/.workbuddy(-ai)`；结束时校验真实文件哈希未变。
- **可复现时间**：涉及「自然日」的断言固定/注入时间源（对齐 `_onboard_due` 的 `now_utc()` 单一时间源），
  避免跨天抖动造成假红。
- **只增不改**：对 `pref`/`onboarded` 做**逐字回归**（与改动前同值），防「只增字段」承诺被悄悄破坏。
- **经验库守门**：SC-010 专门覆盖 EXP-2026-0001（重建 state 静默丢键）。
- **编码**：被测脚本输出仅 ASCII；子进程统一 UTF-8 解码（对齐 `run-all.py` 链路）。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| `tests/test-relay-unified-onboarding.py` | 13 | 集成 | v5.6.0 向导（onboard/onboard set/onboard-status/due/迁移/SC-011 双层） |
| `tests/test-relay-qoder-free-source.py` | 19 | 集成 | v5.6.0 Qoder-free 源 |
| `tests/test-payload-sync-gate.py` | 3 | 集成 | install.sh 载荷字节一致性（EXP-2026-0009） |
| `tests/run-all.py` | 25 脚本 | 聚合 | 全量回归入口（rc=0 表示全绿） |
| 其余 22 个 `test-*.py` | — | 混合 | 安全/并发/校验/调度/治理等既有面 |

> 本 change 新增 `tests/test-relay-agenthub-wiring.py`（TC-AW-001~012）。

## 二、详细测试案例

### 功能 1：派生判据 `agenthub.action`（REQ-APC-001）

#### 案例 1.1 — pref=true & onboarded=false ⇒ prompt_enable

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-001 |
| **对应 Spec** | code spec → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；`state.relay_onboard.agenthub_pref=true`，无 `agenthub_onboarded` |
| **输入** | `pick_model.py onboard-status` |
| **预期结果** | `agenthub.action == "prompt_enable"`；`pref==true`；`onboarded==false` |
| **当前状态** | ❌ 测试缺（实现亦缺） |

#### 案例 1.2 — pref=true & onboarded=true ⇒ none

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-002 |
| **对应 Spec** | code spec → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；`agenthub_pref=true` 且 `state.agenthub_onboarded=true` |
| **输入** | `onboard-status` |
| **预期结果** | `agenthub.action == "none"`；`onboarded==true` |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.3 — pref=false（或缺失）⇒ none

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-003 |
| **对应 Spec** | code spec → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；`agenthub_pref=false`；另跑一组 relay_onboard 缺失（pref=None） |
| **输入** | `onboard-status` |
| **预期结果** | 两组均 `agenthub.action == "none"`（None 不得被当 true） |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.4 — pref=false & onboarded=true ⇒ none

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-004 |
| **对应 Spec** | code spec → Scenario: SC-004 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；`agenthub_pref=false` 且 `agenthub_onboarded=true` |
| **输入** | `onboard-status` |
| **预期结果** | `agenthub.action == "none"` |
| **当前状态** | ❌ 测试缺 |

### 功能 2：防打扰记录 `agenthub.prompted_on`（REQ-APC-002）

#### 案例 2.1 — ack 写入当日且不动其余字段

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-005 |
| **对应 Spec** | code spec → Scenario: SC-005 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；预置完整 `relay_onboard`（含 confirmed_at/groups/custom_periods/agenthub_pref/last_config_hash） |
| **输入** | `onboard agenthub-ack` |
| **预期结果** | `relay_onboard.agenthub_prompted_on == now_utc().date().isoformat()`；其余 5 字段逐字不变；退出码 0 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.2 — ack 幂等

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-006 |
| **对应 Spec** | code spec → Scenario: SC-006 |
| **优先级** | P0 |
| **预置条件** | 同日已 ack 一次 |
| **输入** | 再次 `onboard agenthub-ack` |
| **预期结果** | `agenthub_prompted_on` 仍为该自然日（值不变）；退出码 0 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.3 — relay_onboard 缺失时 ack 安全失败

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-007 |
| **对应 Spec** | code spec → Scenario: SC-007 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；state 无 `relay_onboard` |
| **输入** | `onboard agenthub-ack` |
| **预期结果** | 输出 `ok=false`、`reason="no_relay_onboard"`；state 文件哈希未变；退出码 0 |
| **当前状态** | ❌ 测试缺 |

### 功能 3：文档联动规则（REQ-APC-003）

#### 案例 3.1 — relay_instruction.md 规则可 grep

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-008 |
| **对应 Spec** | code spec → Scenario: SC-008 |
| **优先级** | P1 |
| **预置条件** | 读取 `relay_instruction.md` |
| **输入** | 检索 `prompt_enable` / `agenthub-ack` / `onboarded` 关键串 |
| **预期结果** | 三要点规则均存在（发起 / 跳过 / ack 记录） |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.2 — SKILL.md 规则可 grep

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-009 |
| **对应 Spec** | code spec → Scenario: SC-009 |
| **优先级** | P1 |
| **预置条件** | 读取 `SKILL.md` |
| **输入** | 检索同一组关键串 |
| **预期结果** | 规则与 relay_instruction.md 一致（三要点） |
| **当前状态** | ❌ 测试缺 |

### 功能 4：state 保留与向后兼容（REQ-APC-004 / REQ-UOB-012 / REQ-UOB-013）

#### 案例 4.1 — 策略切换保留 prompted_on（EXP-2026-0001）

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-010 |
| **对应 Spec** | code spec → Scenario: SC-010 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；`relay_onboard.agenthub_prompted_on` 已写 |
| **输入** | `next --strategy fallback`（触发 state 重建）后读 state |
| **预期结果** | `relay_onboard.agenthub_prompted_on` 仍存活；其余 relay_onboard 字段亦保留 |
| **当前状态** | ❌ 测试缺 |

#### 案例 4.2 — agenthub 对象四键 + pref/onboarded 语义不变

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-011 |
| **对应 Spec** | code spec → Scenario: SC-011 |
| **优先级** | P0 |
| **预置条件** | 含 relay_onboard 的临时 HOME（另测 relay_onboard 缺失场景） |
| **输入** | `onboard-status` |
| **预期结果** | `agenthub` 含 `pref/onboarded/action/prompted_on` 四键；缺失时 `action="none"`、`prompted_on=null`；pref/onboarded 值与改动前逐字一致 |
| **当前状态** | ❌ 测试缺 |

#### 案例 4.3 — onboard set 保留既有 prompted_on

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-012 |
| **对应 Spec** | code spec → Scenario: SC-012 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；先 ack（prompted_on=今天） |
| **输入** | `onboard set --json '{"groups":{},"custom_periods":{},"agenthub_pref":true}'` |
| **预期结果** | `relay_onboard.agenthub_prompted_on` 仍为今天；confirmed_at/last_config_hash 正常刷新 |
| **当前状态** | ❌ 测试缺 |

### 功能 2 增补（BUILD 期，见 design-adjustments.md DA-1）

#### 案例 2.4 — ack 适用性门控（action != prompt_enable ⇒ 拒绝且不落盘）

| 字段 | 内容 |
|------|------|
| **ID** | TC-AW-013 |
| **对应 Spec** | code spec → Scenario: SC-005（**收紧**，见 DA-1） |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；组1 `agenthub_pref=false`（action=none）；组2 `pref=true` 且 `agenthub_onboarded=true` |
| **输入** | `onboard agenthub-ack` |
| **预期结果** | 两组均 `ok=false`、`reason="not_applicable"`；state 字节未变；退出码 0 |
| **当前状态** | ✅ 已实现（BUILD 评审 medium 修复） |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E | 状态 |
|----------|---------|----------|-----|------|
| action 派生四态 | ✅ TC-AW-001~004 | ✅ 子进程 CLI | — | 🟡 待实现 |
| prompted_on / ack | ✅ TC-AW-005~007 | ✅ 子进程 CLI | — | 🟡 待实现 |
| 文档规则 | — | ✅ grep 断言 | — | 🟡 待实现 |
| state 保留/兼容 | ✅ TC-AW-010~012 | ✅ 子进程 CLI | — | 🟡 待实现 |
| 全量回归 | — | ✅ `run-all.py` 25/25 | — | 🟢 既有 |

## 四、回归风险矩阵

| 风险区域 | V5.6.1 改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| `onboard-status` 输出契约 | agenthub 对象 +2 键 | `test-relay-unified-onboarding.py`（SC-005~008 状态断言） | 🟢 低（只增） |
| `onboard`（读）输出 | agenthub 对象 +2 键 | 同上（SC-001） | 🟢 低 |
| `onboard set` 写盘 | relay_onboard +carry-over | 同上（SC-003） | 🟡 中（改重建逻辑） |
| CLI 子命令面 | `onboard` action 枚举 +1 | 无（新增分支） | 🟢 低（show/set 不变） |
| 策略切换 state 重建 | 无改动（键在保留集内） | 调度类测试 | 🟢 低 |
| install.sh 载荷 | 无改动（本 change 不动载荷） | `test-payload-sync-gate.py` | 🟢 低 |

## 五、建议补充顺序

1. **第一优先**（部署前必补，P0）：TC-AW-001、002、003、004、005、006、007、010、011、012
2. **第二优先**（部署后尽快补，P1）：TC-AW-008、009
3. **第三优先**（后续补，P2）：无

## 六、证据记录

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| `agenthub_pref` 无消费方（全库检索） | 2026-10-12T23:09:00+08:00 | relay v5.6.0 (tag → 21c7f0f) | proposal.yaml `why.evidence` |
| 保留集仅含 rr_*/free_allowlist/relay_onboard | 2026-10-12T23:20:00+08:00 | relay v5.6.0 (tag → 21c7f0f) | `pick_model.py` L2232-2233 |
| `cmd_onboard_set` 整体重建 relay_onboard | 2026-10-12T23:20:00+08:00 | relay v5.6.0 (tag → 21c7f0f) | `pick_model.py` L4677 |

- `observed_at` 是**信息采集时刻**，不是文档生成时刻。
- 缺 `observed_at` 的证据时效判为「无法判定」（undetermined），**不等同未过期**。

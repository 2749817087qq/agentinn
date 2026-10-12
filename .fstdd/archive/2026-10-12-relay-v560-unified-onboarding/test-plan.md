# 测试方案与详细案例 — relay-v560-unified-onboarding

> 版本：v5.6.0-unified-onboarding
> 创建日期：2026-10-12
> 对应 Phase 2 Spec：canonical/specs/code/2026-10-12-relay-v560-unified-onboarding.yaml、canonical/specs/agent/2026-10-12-relay-v560-unified-onboarding.yaml

## 一、测试策略

### 1.1 测试金字塔

- **单元**（主）：`_onboard_due(confirmed_at, hash, now=)` 纯函数（due 四态）、`migrate_to_relay_onboard(state)`、`_classify_model(m)`（系统/自定义/桥接分类）。
- **集成**（辅）：`onboard`（读）/ `onboard set`（写）/ `onboard-status` / `next` / `inventory` 经临时 HOME 子进程调用。
- **文档/回归**（C1/C2）：grep SKILL.md 新块 + 旧块共存；运行 test-free-model-confirm.py。

### 1.2 测试原则

- 日期判定一律注入 `now`（monkeypatch `now_utc`），不依赖真实时钟（design D4）。
- 桥接扫描用注入探针（`_probe`），不触网（守零阻断）。
- 全部经 `now_utc()` 单一时间源，新代码零 `datetime.now()` 直调（守 TC-TEST-003）。
- 子进程 `_bind_temp` 隔离 HOME，不污染真实 models.json / state。
- 断言仅 ASCII（与 run-all.py `text=True` 解码链路兼容，EXP-2026-0006）。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| D:/tools/多层次agent/tests/test-relay-qoder-free-source.py | 19 | 集成 | Qoder-free 源接入（须保持绿） |
| D:/tools/多层次agent/tests/test-free-model-confirm.py | 多 | 单元+集成 | 免费确认工作流 + install 载荷（**C1 改写后须同步文案断言**） |
| D:/tools/多层次agent/tests/test-doctor-command.py | 20 | 单元 | doctor 命令（须保持绿） |
| D:/tools/多层次agent/tests/run-all.py | — | 编排 | 逐文件 subprocess（text=True 无 encoding） |

## 二、详细测试案例

### 功能 1：onboard（读）汇总（REQ-UOB-001）

#### 案例 1.1 — TC-UOB-001：onboard 输出 system_models + custom_models + agenthub，系统模型标只读

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-001 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME 写含平台模型 + 自定义模型的 models.json |
| **输入** | `onboard` |
| **预期结果** | JSON 含 `system_models`（每条含 start_hour/end_hour + 只读标记）、`custom_models`、`agenthub`；命令只读不改 state/models.json |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.2 — TC-UOB-002：桥接模型尝试扫描免费时段（扫到预填 / 不可达回落 all-day）

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-002 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 存在桥接模型（origins 识别 qoder-free / ow-bridge）；注入探针 |
| **输入** | `onboard`（探针返回时段 / 探针不可达，各一次） |
| **预期结果** | 扫到→custom_models 条目时段预填；不可达→静默回落 all-day，退出码 0 不阻断 |
| **当前状态** | ❌ 测试缺 |

### 功能 2：onboard set（写）（REQ-UOB-002）

#### 案例 2.1 — TC-UOB-003：自定义模型写 window 覆写 + free_allowlist + relay_onboard

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-003 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME；向导结果含自定义模型时段 |
| **输入** | `onboard set`（带 {groups, custom_periods, agenthub_pref}） |
| **预期结果** | override 文件含自定义模型 start/end；state 含 free_allowlist + relay_onboard{confirmed_at,groups,custom_periods,agenthub_pref}；all_day 写 {0,0} |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.2 — TC-UOB-004：系统模型跳过 window 写入

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-004 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-004 |
| **优先级** | P0 |
| **预置条件** | 向导结果含系统模型（_source=platform） |
| **输入** | `onboard set` |
| **预期结果** | override 文件**不含**系统模型条目（宿主规范为准）；退出码 0 不报错 |
| **当前状态** | ❌ 测试缺 |

### 功能 3：onboard-status due 判定（REQ-UOB-003）

#### 案例 3.1 — TC-UOB-005：未确认 → due=true

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-005 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-005 |
| **优先级** | P0 |
| **预置条件** | state 无 relay_onboard |
| **输入** | `onboard-status` |
| **预期结果** | due=true，confirmed_at=null |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.2 — TC-UOB-006：已确认当天且同 hash → due=false

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-006 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-006 |
| **优先级** | P0 |
| **预置条件** | relay_onboard.confirmed_at=今天；last_config_hash == 当前 hash；monkeypatch now_utc 为今天 |
| **输入** | `onboard-status` |
| **预期结果** | due=false，drift_detected=false |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.3 — TC-UOB-007：跨自然日 → due=true

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-007 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-007 |
| **优先级** | P0 |
| **预置条件** | relay_onboard.confirmed_at=昨天；monkeypatch now_utc 为今天 |
| **输入** | `onboard-status` |
| **预期结果** | due=true |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.4 — TC-UOB-008：数据漂移（hash 变）→ due=true

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-008 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-008 |
| **优先级** | P0 |
| **预置条件** | confirmed_at=今天，但 last_config_hash != 当前 hash |
| **输入** | `onboard-status` |
| **预期结果** | due=true，drift_detected=true |
| **当前状态** | ❌ 测试缺 |

### 功能 4：next / inventory 透传（REQ-UOB-004）

#### 案例 4.1 — TC-UOB-009：next/inventory 含 onboard_due

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-009 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-009 |
| **优先级** | P0 |
| **预置条件** | 未确认态；已确认当天态各一次 |
| **输入** | `inventory` 与 `next` |
| **预期结果** | 未确认→onboard_due=true；已确认当天同 hash→onboard_due=false |
| **当前状态** | ❌ 测试缺 |

### 功能 5：存量迁移（REQ-UOB-005）

#### 案例 5.1 — TC-UOB-010：free_allowlist + window 覆写 → relay_onboard，旧键保留

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-010 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-010 |
| **优先级** | P0 |
| **预置条件** | 存量 state 含 free_allowlist + 某自定义模型 window 覆写 |
| **输入** | `onboard`（读）/ `onboard-status` |
| **预期结果** | 派生出 relay_onboard.groups + custom_periods；free_allowlist 旧键保留；脏数据降级为空不报错 |
| **当前状态** | ❌ 测试缺 |

### 功能 6：AgentHub 双层（REQ-UOB-006）

#### 案例 6.1 — TC-UOB-011：agenthub_pref 写入但不写 agenthub_onboarded

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-011 |
| **对应 Spec** | unified-onboarding/spec.md → Scenario: SC-011 |
| **优先级** | P1 |
| **预置条件** | 向导 agenthub 偏好=开 |
| **输入** | `onboard set` |
| **预期结果** | state.relay_onboard.agenthub_pref=true；agenthub_onboarded 未被置真 |
| **当前状态** | ❌ 测试缺 |

### 功能 7：文档与回归同步（C1/C2）

#### 案例 7.1 — TC-UOB-012：SKILL.md 含 relay-onboarding-wizard 块 + 旧 relay-window-wheel 保留

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-012 |
| **对应 Spec** | agent_spec → CP-9 |
| **优先级** | P1 |
| **预置条件** | C1 文档落地 |
| **输入** | grep SKILL.md |
| **预期结果** | 含 `relay-onboarding-wizard:start` 且仍含 `relay-window-wheel:start`（fallback 共存） |
| **当前状态** | ❌ 测试缺 |

#### 案例 7.2 — TC-UOB-013：test-free-model-confirm.py 文案断言同步后通过

| 字段 | 内容 |
|------|------|
| **ID** | TC-UOB-013 |
| **对应 Spec** | agent_spec → CP-10 |
| **优先级** | P1 |
| **预置条件** | C1 改写 + 该测试静态断言同步更新 |
| **输入** | 运行 `tests/test-free-model-confirm.py` |
| **预期结果** | 退出码 0（install 载荷一致性 + 文案断言均绿） |
| **当前状态** | ❌ 测试缺 |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E | 状态 |
|----------|---------|----------|-----|------|
| onboard 读汇总 | — | TC-UOB-001/002 | — | 🔴 待补 |
| onboard set 写 | — | TC-UOB-003/004 | — | 🔴 待补 |
| due 判定 | TC-UOB-005~008 | — | — | 🔴 待补 |
| 透传 | — | TC-UOB-009 | — | 🔴 待补 |
| 迁移 | TC-UOB-010 | — | — | 🔴 待补 |
| AgentHub | — | TC-UOB-011 | — | 🔴 待补 |
| 文档/回归 | — | TC-UOB-012/013 | — | 🔴 待补 |

## 四、回归风险矩阵

| 风险区域 | V5.6.0 改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| Step 0 文档文案 | C1 新增向导块 + 改写 | test-free-model-confirm.py 静态断言（须同步） | 🟡 中 |
| window 命令 | 复用不改签名（仅 onboard 调用） | 既有 window 测试套件 | 🟢 低 |
| install 载荷一致性 | SKILL.md/pick_model.py 改动 | _sync_install_payload + verify_payload + tc_fmc_014 | 🟢 低 |
| 时间源单一性 | 新增 due 逻辑须走 now_utc | TC-TEST-003 | 🟢 低 |
| Qoder-free 源（上游） | 复用 origins 分类 | test-relay-qoder-free-source.py 19/19 | 🟢 低 |
| free_allowlist 兼容 | 保留旧键只读 | TC-FMC-005（state 重建保留） | 🟢 低 |

## 五、建议补充顺序

1. **第一优先**（部署前必补）：TC-UOB-001 / 003 / 004 / 005 / 006 / 007 / 008 / 009（P0：读汇总、写、系统跳过、due 四态、透传）。
2. **第二优先**（部署后尽快补）：TC-UOB-002 / 010 / 011 / 012 / 013（P1：桥接扫描、迁移、AgentHub 双层、文档与回归同步）。
3. **第三优先**（后续补）：无。

## 六、证据记录

> 每条引用实测数据的证据必须可定位**观测时刻**与**代码版本**（TC-EPR-002）。

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| 旧 relay-window-wheel 渲染（截图） | 2026-10-12T20:14:00+08:00 | — | 用户截图 Clipboard_Screenshot.png |
| v5.5.0 扫描器 by_id=42 free_ids=['hy3'] | 2026-10-12T20:20:00+08:00 | — | v5.5.0 扫描器实测（memory 2026-10-12） |
| window.per_model = _per_model_window_view() | 2026-10-12T20:45:00+08:00 | — | pick_model.py L507（静态代码观测） |
| is_free_window 逐模型 + 扫描器短路 | 2026-10-12T20:45:00+08:00 | — | pick_model.py L559-604 |
| window set --model 逐模型覆写 | 2026-10-12T20:45:00+08:00 | — | pick_model.py L4073-4133 |

- `observed_at` 是**信息采集时刻**，不是文档生成时刻（generated_at 与此无关）。
- 缺 `observed_at` 的证据时效判为「无法判定」（undetermined），**不等同未过期**。

# 测试方案与详细案例 — relay-v560-daily-free-confirm

> 版本：v5.6.0-daily-confirm
> 创建日期：2026-10-12
> 对应 Phase 2 Spec：canonical/specs/code/2026-10-12-relay-v560-daily-free-confirm.yaml、canonical/specs/agent/2026-10-12-relay-v560-daily-free-confirm.yaml

## 一、测试策略

### 1.1 测试金字塔

- **单元**（主）：`_free_confirm_status(confirmed_at, now=)` 纯函数，覆盖 SC-001~004 的日期/脏数据分支，全部注入 `now` 不依赖墙上时钟。
- **集成**（辅）：`free confirm-status` / `free set` / `free clear` / `next` / `inventory` 经临时 HOME 子进程调用，验证命令层与透传字段（SC-005~008）。
- **文档断言**（C2）：grep SKILL.md / relay_instruction.md 文案 + 回归 `test-free-model-confirm.py`（CP-8/CP-9）。

### 1.2 测试原则

- 日期判定一律注入 `now`（monkeypatch `now_utc` 或 helper 入参），绝不依赖真实时钟（守 determinism，design D1）。
- 全部经 `now_utc()` 单一时间源，新代码零 `datetime.now()` 直调（守 TC-TEST-003）。
- 子进程调用 `_bind_temp` 隔离 HOME，不污染真实 models.json / state。
- 断言仅 ASCII（与 run-all.py `text=True` 解码链路兼容，EXP-2026-0006）。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| D:/tools/多层次agent/tests/test-relay-qoder-free-source.py | 19 | 集成 | Qoder-free 源接入（本 change 上游，须保持绿） |
| D:/tools/多层次agent/tests/test-free-model-confirm.py | 多 | 单元+集成 | 免费确认工作流 + install 载荷一致性（**C2 改写后须同步更新静态断言**） |
| D:/tools/多层次agent/tests/test-doctor-mutation.py | 多 | 单元 | doctor 命令（FMR_QF_AUTODISCOVER 防护，须保持绿） |
| D:/tools/多层次agent/tests/run-all.py | — | 编排 | 逐文件 subprocess，text=True 无 encoding（子进程中文需 utf-8 解码） |

## 二、详细测试案例

### 功能 1：free confirm-status 每日闸判定（REQ-DFC-001）

#### 案例 1.1 — TC-DFC-001：未确认 → due=true（只读）

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-001 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME 干净 state（无 free_allowlist） |
| **输入** | `free confirm-status` |
| **预期结果** | 输出 JSON：`due=true`、`confirmed_at=null`、`confirmed_date=null`、`state=unset`、`count=0`；state 文件未被修改 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.2 — TC-DFC-002：已确认且为今天 → due=false

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-002 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | state 写 `free_allowlist={ids:["x"],confirmed_at:<今天本地 ISO>}`；monkeypatch `now_utc` 为今天 |
| **输入** | `free confirm-status` |
| **预期结果** | `due=false`、`confirmed_date == today`、`confirmed_at` 原样回显 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.3 — TC-DFC-003：已确认但跨天（昨天）→ due=true

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-003 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | state 写 `confirmed_at=<昨天本地 ISO>`；monkeypatch `now_utc` 为今天 |
| **输入** | `free confirm-status` |
| **预期结果** | `due=true`、`confirmed_date != today` |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.4 — TC-DFC-004：脏 confirmed_at → due=true 且原值保留

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-004 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-004 |
| **优先级** | P1 |
| **预置条件** | state 写 `confirmed_at="not-a-date"` |
| **输入** | `free confirm-status` |
| **预期结果** | `due=true`、`confirmed_at` 回显 `"not-a-date"`；退出码 0、不抛异常 |
| **当前状态** | ❌ 测试缺 |

### 功能 2：next / inventory 透传 free_confirm_due（REQ-DFC-002）

#### 案例 2.1 — TC-DFC-005：未确认态 free_confirm_due=true；已确认今天态 free_confirm_due=false

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-005 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-005 / SC-006 |
| **优先级** | P0 |
| **预置条件** | Case A：临时 HOME 干净 state；Case B：写已确认今天 + monkeypatch `now_utc` 为今天；并预置至少 1 条 declared 模型 |
| **输入** | 两次分别执行 `inventory` 与 `next`（auto） |
| **预期结果** | Case A 输出含 `free_confirm_due=true`；Case B 输出含 `free_confirm_due=false`；inventory 的 `free_allowlist.confirmed_at` 与态一致 |
| **当前状态** | ❌ 测试缺 |

### 功能 3：free set / clear 维护每日闸（REQ-DFC-003）

#### 案例 3.1 — TC-DFC-006：free set 重置当日已确认（set 后 confirm-status due=false）

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-006 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-007 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME 干净 state；monkeypatch `now_utc` 为今天；预置 1 条 declared 模型 id |
| **输入** | `free set --ids <valid-id>` 后紧接 `free confirm-status` |
| **预期结果** | confirm-status `due=false`；`next`/`inventory` 的 `free_confirm_due=false` |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.2 — TC-DFC-007：free clear 使次日重新到期（clear 后 confirm-status due=true）

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-007 |
| **对应 Spec** | free-daily-confirm/spec.md → Scenario: SC-008 |
| **优先级** | P0 |
| **预置条件** | state 写已确认今天（`ids:["x"],confirmed_at:<今天 ISO>`） |
| **输入** | `free clear` 后紧接 `free confirm-status` |
| **预期结果** | confirm-status `due=true`、`state=unset` |
| **当前状态** | ❌ 测试缺 |

### 功能 4：C2 文档改写与测试维护（agent_spec CP-8/CP-9）

#### 案例 4.1 — TC-DFC-008：SKILL.md / relay_instruction.md 文案由「每次触发」改为「每天首次触发 + free_confirm_due」

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-008 |
| **对应 Spec** | agent_spec → CP-8 |
| **优先级** | P1 |
| **预置条件** | C2 文档改写落地 |
| **输入** | grep SKILL.md / relay_instruction.md |
| **预期结果** | 含「每天首次触发」「free_confirm_due」；不含「每次触发都弹窗确认」「每次触发都做」 |
| **当前状态** | ❌ 测试缺 |

#### 案例 4.2 — TC-DFC-009：test-free-model-confirm.py 静态断言同步（不再因旧文案红）

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFC-009 |
| **对应 Spec** | agent_spec → CP-9 |
| **优先级** | P1 |
| **预置条件** | C2 改写 + 该测试静态断言同步更新 |
| **输入** | 运行 `tests/test-free-model-confirm.py` |
| **预期结果** | 退出码 0（install 载荷一致性 TC 与文案断言均绿） |
| **当前状态** | ❌ 测试缺 |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E | 状态 |
|----------|---------|----------|-----|------|
| confirm-status 判定（C1） | TC-DFC-001/002/003/004 | — | — | 🔴 待补 |
| next/inventory 透传（C1） | — | TC-DFC-005 | — | 🔴 待补 |
| set/clear 维护闸（C1） | — | TC-DFC-006/007 | — | 🔴 待补 |
| 文档改写 + 测试维护（C2） | — | TC-DFC-008/009 | — | 🔴 待补 |

## 四、回归风险矩阵

| 风险区域 | V5.6.0 改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| 免费确认工作流文案 | C2 改写「每次触发」→「每天首次触发」 | test-free-model-confirm.py 静态断言（须同步，否则红） | 🟡 中 |
| install 载荷一致性 | pick_model.py 改动须经 _sync_install_payload + verify_payload | tc_fmc_014_install_payload_identical | 🟢 低 |
| 时间源单一性 | 新增日期逻辑须走 now_utc | TC-TEST-003（datetime.now 只许 1 次） | 🟢 低 |
| Qoder-free 源（上游 change） | 本 change 不动其代码，但同脚本 | test-relay-qoder-free-source.py 19/19 | 🟢 低 |
| state 策略切换保留白名单 | 复用既有 confirmed_at，不新增键 | TC-FMC-005（state 重建保留 FREE_ALLOWLIST_KEY） | 🟢 低 |

## 五、建议补充顺序

1. **第一优先**（部署前必补）：TC-DFC-001 / 002 / 003 / 005 / 006 / 007（P0，覆盖判定四态、透传、set/clear 重置）。
2. **第二优先**（部署后尽快补）：TC-DFC-004 / 008 / 009（P1，脏数据防御、文档改写与测试维护）。
3. **第三优先**（后续补）：无。

## 六、证据记录

> 每条引用实测数据的证据必须可定位**观测时刻**与**代码版本**（TC-EPR-002）。

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| free_allowlist 存储结构（ids/confirmed_at） | 2026-10-12T18:40:00+08:00 | — | pick_model.py L1790-1819（静态代码观测） |
| free set 写 confirmed_at=now_utc() | 2026-10-12T18:40:00+08:00 | — | pick_model.py L2157-2166 |
| free clear 清 confirmed_at=None | 2026-10-12T18:40:00+08:00 | — | pick_model.py L2110-2125 |
| now_utc 为唯一时间源（datetime.now 单点） | 2026-10-12T18:41:00+08:00 | — | pick_model.py L148-153 + L3377（TC-TEST-003 约束） |

- `observed_at` 是**信息采集时刻**，不是文档生成时刻（generated_at 与此无关）。
- 缺 `observed_at` 的证据时效判为「无法判定」（undetermined），**不等同未过期**。

# v5.6.0 测试方案与详细案例

> 版本：relay-v560-qoder-free-source
> 创建日期：2026-10-12
> 对应 Phase 2 Spec：canonical/specs/code/2026-10-12-relay-v560-qoder-free-source.yaml

## 一、测试策略

### 1.1 测试金字塔

- **单元（≈65%）**：`discover_qoder_free` 的探测 / 写入 / 幂等 / 失败分支，以及 `_detect_source_tool` 的
  source 归因——均通过 `importlib` 加载被测模块 + `unittest.mock` 替换 HTTP 调用，**不触网**、不改真实文件。
- **集成（≈30%）**：`relay next` / `inventory` / `scan` / `origins` 经 `subprocess` 调被测脚本、HOME 指向临时目录，
  验证「默认进池」「origins 归类」「TTL 不重复联网」端到端。
- **E2E（≈5%，可选/手动）**：对真实 Qoder-free（D:/tools/qoder-free 已启动且加账号）跑一次 `relay qoder-free sync`
  确认能拉到模型；不作为 CI 必跑（依赖本机网关状态）。

### 1.2 测试原则

- 零触网：单测一律 mock HTTP；集成测用临时 HOME，断言只用 ASCII（与 `run-all.py` 的 `text=True` + UTF-8 解码链路兼容，
  见 `test-relay-source-governance.py` 的 `run_script`）。
- 真实 HOME 守卫：用例前后比对 `~/.workbuddy` 下 models.json/state/usage/window 的 sha256，确保不被改动。
- 失败静默：discover 在不可达 / config 缺失时不得污染 stdout，否则既有 `next`/`inventory` 用例会变红。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| tests/test-relay-ownership.py | 4+ | 单元+集成 | `*Owner` 判定口径（SC-MO-019/020/021），复用其 `_make_home`/`_write_models`/`models add` 守卫范式 |
| tests/test-relay-source-governance.py | 13 | 单元+集成 | origins 归因 + 双根自适应（TC-MSD-001~005 可直接扩展验证 qoder-free 源） |
| tests/test-program-cache-scanner.py | — | 集成 | v5.5.0 扫描器（free_ids → all 源），本变更不改其逻辑但需确认零回归 |

## 二、详细测试案例

### 功能 1：discover_qoder_free 探测与写入（C1 / REQ-DISCOVER-001）

#### 案例 1.1 — TC-QF-001：探测成功写 Custom 条目

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-001 |
| **对应 Spec** | REQ-DISCOVER-001 → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | mock `GET /v1/models` 返回 `{"data":[{"id":"cn:qoder-free-x"}]}`；临时 HOME 无该 id 条目 |
| **输入** | 调用 `discover_qoder_free(home=tmp)`（或 `relay qoder-free sync`） |
| **预期结果** | models.json 出现 `{id:"cn:qoder-free-x", vendor:"Custom", url:"http://127.0.0.1:8210/v1", apiKey:<QF>, qoderFreeOwner:"qoder-free"}`；stdout 含 `qoderFreeOwner`；apiKey 仅经 `_mask_secret` 输出 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.2 — TC-QF-007：幂等 upsert（同 id 不重复；异 owner 不覆盖）

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-007 |
| **对应 Spec** | REQ-DISCOVER-001 → Scenario: SC-002 |
| **优先级** | P1 |
| **预置条件** | 已有一条 `qoderFreeOwner` 的 `cn:qoder-free-x` 条目；另有一条 `relayOwner` 的 `cn:qoder-free-y` 条目 |
| **输入** | 再跑一次 `discover_qoder_free` |
| **预期结果** | `cn:qoder-free-x` 数组长度不变（仅更新 url/key）；`cn:qoder-free-y` 不被覆盖（保留 relayOwner） |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.3 — TC-QF-002：端点不可达静默跳过

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-002 |
| **对应 Spec** | REQ-DISCOVER-001 → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | Qoder-free 未启动（base 指向不可达地址） |
| **输入** | `cmd_next` / `relay qoder-free sync` 触发发现 |
| **预期结果** | 退出码 0；stdout 为空（不报错）；models.json 不变；relay 正常返回既有模型 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.4 — TC-QF-008：config 缺失静默跳过 + 环境变量覆盖

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-008 |
| **对应 Spec** | REQ-DISCOVER-001 → Scenario: SC-004 |
| **优先级** | P1 |
| **预置条件** | config 路径不存在（默认与覆盖路径均缺失） |
| **输入** | 触发发现；再以 `QODER_FREE_CONFIG` 指向合法 config 触发 |
| **预期结果** | 缺失时静默跳过（退出 0、不写文件）；覆盖路径生效时能正常探测 |
| **当前状态** | ❌ 测试缺 |

### 功能 2：自动触发 + TTL 缓存（C1 / REQ-DISCOVER-002）

#### 案例 2.1 — TC-QF-006：TTL 内不重复联网

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-006 |
| **对应 Spec** | REQ-DISCOVER-002 → Scenario: SC-005 |
| **优先级** | P1 |
| **预置条件** | mock probe 计数；STATE_FILE 中 `qoder_free_last_discovery` 距今 < 60s |
| **输入** | 连续两次 `cmd_next`（间隔 < TTL） |
| **预期结果** | probe 仅被调用 1 次（首次）；第二次在 TTL 内不再联网；TTL 过期后下一次重探 1 次 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.2 — TC-QF-009：scan 冷路径触发发现

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-009 |
| **对应 Spec** | REQ-DISCOVER-002 → Scenario: SC-006 |
| **优先级** | P2 |
| **预置条件** | Qoder-free 已启动 + TTL 已过期（或 mock） |
| **输入** | `relay scan` |
| **预期结果** | 扫描前先执行一次发现，新发现的 Qoder-free 模型被纳入 `known_models` 增量 |
| **当前状态** | ❌ 测试缺 |

### 功能 3：origins 来源归类（C2 / REQ-ORIGINS-001）

#### 案例 3.1 — TC-QF-003：origins 归类为 qoder-free 源

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-003 |
| **对应 Spec** | REQ-ORIGINS-001 → Scenario: SC-007 |
| **优先级** | P0 |
| **预置条件** | 临时 HOME 的某 data-root models.json 含 `qoderFreeOwner:"qoder-free"` 的 Custom 条目 |
| **输入** | `relay origins` |
| **预期结果** | 该 root 的 `tool` == `"qoder-free"`、`tool_detail` == `"Qoder-free"`；`free_semantics` == `"quota(third-party-managed)"`；不被误判为 relay/ow-bridge/external |
| **当前状态** | ❌ 测试缺 |

### 功能 4：默认进免费候选池（C3 / REQ-POOL-001）

#### 案例 4.1 — TC-QF-004：inventory 列出且 next 默认返回（无需 allowlist）

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-004 |
| **对应 Spec** | REQ-POOL-001 → Scenario: SC-008 |
| **优先级** | P0 |
| **预置条件** | models.json 含 `qoderFreeOwner` 的 Custom 条目；用户未做 allowlist 勾选 |
| **输入** | `relay inventory` 与 `relay next --source auto` |
| **预期结果** | inventory `declared` 列出该条目（`default_free=True`）；next 不勾选 allowlist 也能返回它，`recommended_prefix` == `"custom-local:"` |
| **当前状态** | ❌ 测试缺 |

### 功能 5：零密钥泄漏（C4 / REQ-SEC-001）

#### 案例 5.1 — TC-QF-005：对外输出不含 apiKey 明文

| 字段 | 内容 |
|------|------|
| **ID** | TC-QF-005 |
| **对应 Spec** | REQ-SEC-001 → Scenario: SC-009 |
| **优先级** | P0 |
| **预置条件** | models.json 含带真实 apiKey 的 `qoderFreeOwner` 条目 |
| **输入** | `relay list` / `inventory` / `profile` / `origins`（及 policy 快照若存在） |
| **预期结果** | 任何 stdout 输出均不出现 apiKey 明文；apiKey 仅以 `_mask_secret` 遮蔽形态或完全不出现 |
| **当前状态** | ❌ 测试缺 |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E | 状态 |
|----------|---------|----------|-----|------|
| discover 探测/写入（C1） | TC-QF-001/007 | TC-QF-002/008 | TC-QF-009 | 🟡 待补 |
| 自动触发+TTL（C1） | TC-QF-006 | — | — | 🟡 待补 |
| origins 归类（C2） | — | TC-QF-003 | — | 🟡 待补 |
| 默认进池（C3） | — | TC-QF-004 | — | 🟡 待补 |
| 零泄漏（C4） | — | TC-QF-005 | — | 🟡 待补 |

## 四、回归风险矩阵

| 风险区域 | V5.6.0 改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| `_detect_source_tool` / origins | 新增 qoder-free 分支 | test-relay-source-governance.py TC-MSD-003（ow-bridge 归因不变） | 🟢 |
| `load_models` / 候选池 | 无改动（仅新增条目） | test-relay-ownership.py / scheduler 用例 | 🟢 |
| `cmd_next` 冷路径发现 | 新增 best-effort 探测 | test-scheduler-contract-and-cost.py（输出契约） | 🟡（需确认无 stderr 噪声） |
| `models add` 所有权守卫 | 无改动 | test-relay-ownership.py TC-MO-019/020/021 | 🟢 |
| 双根解析 | 无改动 | test-relay-source-governance.py TC-DRA-001~006 | 🟢 |

## 五、建议补充顺序

1. **第一优先**（部署前必补）：TC-QF-001 / 002 / 003 / 004 / 005（P0，覆盖发现写条目、不可达跳过、origins 归类、默认进池、零泄漏）。
2. **第二优先**（部署后尽快补）：TC-QF-006 / 007 / 008（TTL、幂等、config 覆盖）。
3. **第三优先**（后续补）：TC-QF-009（真实网关 scan 端到端，依赖本机状态）。

## 六、证据记录

> 每条引用实测数据的证据必须可定位**观测时刻**与**代码版本**（TC-EPR-002）。

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| Qoder-free 安装与 /v1/models 实测（带 key→200 标准格式） | 2026-10-12T18:25:00+08:00 | Qoder-free v0.1.0 (c092402) | deliverables/qoder-free-digest-2026-10-11.md + 本会话实测 |
| relay 代码核对：load_models Custom 全量纳入 / resolve_source / cmd_next 前缀 | 2026-10-12T18:30:00+08:00 | relay v5.5.0 | pick_model.py L1596-1599 / L1690-1704 / L2318 |
| `*Owner` 后缀判定口径（REQ-MO-008） | 2026-10-11 | relay v5.5.0 | pick_model.py L3449-3474 |

- `observed_at` 是**信息采集时刻**，不是文档生成时刻。
- 缺 `observed_at` 的证据时效判为「无法判定」（undetermined），**不等同未过期**。

# free-model-relay → agentinn 测试方案与详细案例

> 版本：v5.7.0（改名版）
> 创建日期：2026-10-13
> 对应 Phase 2 Spec：`agentinn-rename`、`data-file-migration`（canonical YAML + Human View）
> 基线：`23f8b7d`（relay v5.6.1）

## 一、测试策略

### 1.1 测试金字塔

- **静态断言（主力）**：改名类改动的正确性主要由**静态守卫**保证 —— 排除区外无旧名（内容 + 文件名）、关键处有新名、
  替换引擎幂等。这类断言成本低、覆盖广、可反复执行。
- **集成测试**：数据迁移三态 + owner 双值三态（走 `pick_model.py` 真实调用，隔离 HOME）。
- **冒烟（E2E）**：`agentinn <cmd>` 与直调等价（真实子命令，非 `--help`）。

### 1.2 测试原则

- **双向断言**：既断言新名存在，也断言旧名不存在（防「改名 = 删除」假绿）。
- **检测串拼接构造**：`BAD = "free-" + "model-relay"`，避免断言脚本自检出自检。
- **断言脚本自身排除**；**排除区显式声明 + 逐条理由**。
- **文件名维度单独扫**（内容断言扫不到文件名）。
- **反向验证**：每条断言人为制造失败确认会红（防空断言）。
- **隔离 HOME**：所有真实调用在临时 HOME 下，测试前后比对真实 HOME 哈希（守卫）。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| `tests/test-relay-agenthub-wiring.py` | 13 | 集成 | AgentHub 接线（v5.6.1） |
| `tests/test-relay-unified-onboarding.py` | 18 | 集成 | 统一启用向导 |
| `tests/test-payload-sync-gate.py` | 3 | 集成 | install.sh 载荷一致性 + 双根字节一致 |
| `tests/test-fmr-doc-sample.py` | 5 | 集成 | SKILL.md 文档样例 |
| `tests/run-all.py` | 26 脚本 | 聚合 | 全量回归 |

## 二、详细测试案例

### 功能 1：agentinn-rename（标识/目录/入口改名）

#### 案例 1.1 — 仓库内无旧名字面

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-001 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 改名后的 SKILL.md / relay_instruction.md / scripts/pick_model.py |
| **输入** | grep 旧名字面（排除区外） |
| **预期结果** | 0 命中；且新名 `agentinn` 各文件 ≥1 命中 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.2 — frontmatter name 与文档示例

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-002 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 改名后的 SKILL.md |
| **输入** | 读 frontmatter + grep 用法示例 |
| **预期结果** | `name: agentinn`；示例为 `agentinn <cmd>` |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.3 — 文件名维度（含数据文件名与 skill 目录名）

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-003 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | 改名后的仓库与安装目录 |
| **输入** | 递归枚举排除区外的文件/目录名并检索旧名 |
| **预期结果** | 0 命中；`*.bak-*` 被排除 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.4 — 替换引擎幂等

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-004 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-004 |
| **优先级** | P0 |
| **预置条件** | 替换引擎 + 已改名文本 |
| **输入** | 对已改名文本再次执行替换引擎 |
| **预期结果** | 输出 == 输入（幂等）；左边界不误伤 `agentinn-*` |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.5 — agentinn 入口与直调等价

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-005 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-005 |
| **优先级** | P0 |
| **预置条件** | 已安装 `agentinn`；隔离 HOME |
| **输入** | `agentinn status` vs `python <skill>/scripts/pick_model.py status` |
| **预期结果** | 输出逐字一致；退出码一致 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.6 — 入口零交互（非 TTY）

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-006 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-006 |
| **优先级** | P0 |
| **预置条件** | stdin 为管道（非 TTY） |
| **输入** | `agentinn status`（管道上下文） |
| **预期结果** | 正常返回、不阻塞、不读 stdin |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.7 — 两根目录均为 agentinn/

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-007 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-007 |
| **优先级** | P0 |
| **预置条件** | 目录改名完成后 |
| **输入** | 列出两根 `skills/` |
| **预期结果** | 存在 `agentinn/` 且不存在 `free-model-relay/` |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.8 — 历史快照保留旧名（未误伤）

| 字段 | 内容 |
|------|------|
| **ID** | TC-ARN-008 |
| **对应 Spec** | agentinn-rename/spec.md → Scenario: SC-008 |
| **优先级** | P1 |
| **预置条件** | 排除区（归档/审计/历史日志） |
| **输入** | grep 排除区内容 |
| **预期结果** | 仍含旧名（未被改写） |
| **当前状态** | ❌ 测试缺 |

### 功能 2：data-file-migration（数据文件迁移 + 标记兼容）

#### 案例 2.1 — 新文件名生成

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-001 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-009 |
| **优先级** | P0 |
| **预置条件** | 空数据根（隔离 HOME） |
| **输入** | `free set --ids a` |
| **预期结果** | 生成 `agentinn-state.json`；不生成旧名文件 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.2 — 旧文件迁移（只读旧写新不删旧）

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-002 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-010 |
| **优先级** | P0 |
| **预置条件** | 仅有旧 state 文件 |
| **输入** | `status` |
| **预期结果** | 生成新文件（内容等价）；旧文件仍存在 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.3 — 旧缺失正常返回

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-003 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-011 |
| **优先级** | P0 |
| **预置条件** | 空数据根 |
| **输入** | `status` |
| **预期结果** | 退出码 0，不报错 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.4 — 新旧并存以新为准

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-004 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-012 |
| **优先级** | P0 |
| **预置条件** | 新旧文件并存（内容不同） |
| **输入** | `status` |
| **预期结果** | 新文件字节不变（未被旧覆盖） |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.5 — 迁移幂等

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-005 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-013 |
| **优先级** | P0 |
| **预置条件** | 已迁移一次 |
| **输入** | 再次执行同一命令 |
| **预期结果** | 新文件字节不变；无额外副本 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.6 — 旧 owner 值识别为 relay

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-006 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-014 |
| **优先级** | P0 |
| **预置条件** | models.json 条目带 `relayOwner:"free-model-relay"` |
| **输入** | 所有权判定路径 |
| **预期结果** | 识别为 relay（不被判 external） |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.7 — 新 owner 值识别为 relay

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-007 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-015 |
| **优先级** | P0 |
| **预置条件** | models.json 条目带 `relayOwner:"agentinn"` |
| **输入** | 所有权判定路径 |
| **预期结果** | 识别为 relay；新写入值为 `agentinn` |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.8 — 不误伤其它 owner

| 字段 | 内容 |
|------|------|
| **ID** | TC-DFM-008 |
| **对应 Spec** | data-file-migration/spec.md → Scenario: SC-016 |
| **优先级** | P0 |
| **预置条件** | 条目带 `qoderFreeOwner` / `buddyBridgeOwner` |
| **输入** | 所有权判定路径 |
| **预期结果** | 判 external（非 relay） |
| **当前状态** | ❌ 测试缺 |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E | 状态 |
|----------|---------|----------|-----|------|
| 标识/文档改名 | TC-ARN-001/002 | — | — | 🔴 待建 |
| 文件名维度 | TC-ARN-003 | — | — | 🔴 待建 |
| 替换引擎 | TC-ARN-004 | — | — | 🔴 待建 |
| agentinn 入口 | — | TC-ARN-005/006 | TC-ARN-005 | 🔴 待建 |
| 目录改名 | — | TC-ARN-007 | — | 🔴 待建 |
| 历史快照 | TC-ARN-008 | — | — | 🔴 待建 |
| 数据迁移 | — | TC-DFM-001~005 | — | 🔴 待建 |
| owner 兼容 | — | TC-DFM-006~008 | — | 🔴 待建 |

## 四、回归风险矩阵

| 风险区域 | 本次改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| `scripts/pick_model.py` 数据路径 | 文件名常量改名 + 迁移函数 | `test-data-integrity.py`、`test-relay-unified-onboarding.py` | 🟡 中 |
| 所有权判定 | 双值集合 | `test-relay-ownership.py`、`test-relay-models-onboarding.py` | 🟡 中 |
| install.sh 载荷 | 安装路径 + 内嵌改名 | `test-payload-sync-gate.py`、`verify_payload.py` | 🔴 高（EXP-0003 必踩区） |
| SKILL.md 文档 | 15 处改名 | `test-fmr-doc-sample.py` | 🟡 中 |
| skill 目录名 | 改名（DELIVER 最后） | 无（须新增） | 🔴 高 |
| 用户数据文件 | 迁移 | 无（须新增） | 🟡 中 |

## 五、建议补充顺序

1. **第一优先**（部署前必补，P0）：TC-ARN-001、TC-ARN-002、TC-ARN-003、TC-ARN-004、TC-ARN-005、TC-ARN-006、TC-ARN-007、TC-DFM-001、TC-DFM-002、TC-DFM-003、TC-DFM-004、TC-DFM-005、TC-DFM-006、TC-DFM-007、TC-DFM-008
2. **第二优先**（部署后尽快补，P1）：TC-ARN-008
3. **第三优先**（后续补，P2）：无

## 六、证据记录

> 每条引用实测数据的证据必须可定位**观测时刻**与**代码版本**（TC-EPR-002）。

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| 侦察命中数（SKILL.md 15 / relay_instruction.md 10 / pick_model.py 7） | 2026-10-13T07:40:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `grep -rn free-model-relay` |
| 家目录旧数据文件清单 | 2026-10-13T07:40:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `ls ~/.workbuddy \| grep relay` |
| 其它 skill / AGENTS.md 0 命中 | 2026-10-13T07:41:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `grep -rln` 两根 skills |
| models.json 无 relayOwner 条目 | 2026-10-13T07:41:00+08:00 | 23f8b7d1966e02b9fa683ff089b3ff539d691ece | `grep -o '"relayOwner"...'` |

- `observed_at` 是**信息采集时刻**，不是文档生成时刻（generated_at 与此无关）。

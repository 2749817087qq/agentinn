# free-model-relay v5.5.0 测试方案与详细案例（Phase 2 SPEC）

> 版本：v5.5.0
> 创建日期：2026-10-11
> 对应 Phase 2 Spec：scan_program_config / build_candidate_pool / resolve_free_window_next

## 一、测试策略

### 1.1 测试金字塔

- **单元（≈75%）**：扫描器字段解析、effective 计算、跨午夜时段、降级分支、候选池组装、next 前缀逻辑 —— 全部可注入 `now` 与缓存样例，**不触网、不触真实 models.json**。
- **集成（≈20%）**：`resolve_source` 消费扫描器、`cmd_next` 端到端输出裸 id。
- **E2E / 文档校验（≈5%）**：SKILL.md 无残留硬编码窗口（`grep` + `fstdd validate`）。

### 1.2 测试原则

- 不变量优先：任何降级路径**不得静默空清单**（C5/SC2）。
- 双根合并保守：同 id 取更低 effective，避免把收费当免费。
- 折扣 ≠ 免费：`free_now` 严格 `effective == 0`。
- 程序模型裸 id；`custom-local:` 仅 BYOK 兜底。

### 1.3 已有测试资产

| 测试文件 | 用例数 | 类型 | 覆盖范围 |
|----------|--------|------|----------|
| tests/test-doctor-command.py | 多 | 单元/集成 | 现有 is_free_window / resolve_source 行为（须扩展） |
| tests/test-fmr-doc-sample.py | 5 | 单元 | SKILL.md 同步断言（TC-RFN-005 可挂此） |
| tests/test-scheduler-contract-and-cost.py | 24 | 单元 | 调度契约 + 三份载荷一致（回归防护） |

## 二、详细测试案例

### 功能 1：scan_program_config（双根缓存扫描器）

#### 案例 1.1 — TC-SCAN-001（SC1 / SC5）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-001 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 双根缓存均存在且字段完整；注入 now 在 hy3 全天窗 + hy4-preview 夜间窗 |
| **输入** | `scan_program_config(roots=[rootA, rootB], now=now)` |
| **预期结果** | 含 hy3(free_now=True, window=null, valid_until=2026-11-01) 与 hy4-preview(free_now=True, window={start:23,end:8}, valid_until=2026-11-01)；条目含 base/effective/free_now/source_root |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.2 — TC-SCAN-002（SC6）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-002 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 同 id 在 rootA base x0.29、rootB base x0.00（AI 根 deepseek-v4.1-flash 情形） |
| **输入** | 扫描器合并双根同 id 模型 |
| **预期结果** | 合并 effective 取更低（x0.00）；source_root 标记来源 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.3 — TC-SCAN-003（SC5）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-003 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-003 |
| **优先级** | P1 |
| **预置条件** | glm-5.2 配置夜间 discountedCredits x0.50；now 在夜间窗 |
| **输入** | `scan_program_config` 处理折扣模型 |
| **预期结果** | free_now=False（effective≠0），但出现在折扣清单且 effective_credits 反映 0.5x |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.4 — TC-SCAN-004（SC2）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-004 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-004 |
| **优先级** | P0 |
| **预置条件** | 仅一根缓存缺失、另一根正常 |
| **输入** | 逐根读取 |
| **预期结果** | 跳过缺失根并记 warning；结果非空且 warnings[] 标记被跳过根 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.5 — TC-SCAN-005（SC2 / C5）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-005 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-005 |
| **优先级** | P0 |
| **预置条件** | 双根均缺失或双根字段完全无法解析 |
| **输入** | 扫描器判定整体不可用 |
| **预期结果** | 显式告警并回退 models.json freeWindow 链（非空）；models.json 亦缺失时非零退出 |
| **当前状态** | ❌ 测试缺 |

#### 案例 1.6 — TC-SCAN-006（C5）

| 字段 | 内容 |
|------|------|
| **ID** | TC-SCAN-006 |
| **对应 Spec** | scan_program_config/spec.md → Scenario: SC-006 |
| **优先级** | P1 |
| **预置条件** | 某根缓存存在但单条模型缺 credits 字段 |
| **输入** | 解析该模型 |
| **预期结果** | 标记 degraded 并跳过，不中断整次扫描；degraded 列表包含在返回结果 |
| **当前状态** | ❌ 测试缺 |

### 功能 2：build_candidate_pool（候选池）

#### 案例 2.1 — TC-POOL-001（SC3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-POOL-001 |
| **对应 Spec** | build_candidate_pool/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 扫描器产出 [hy3, hy4-preview]（free_now=True） |
| **输入** | `build_free_candidate_pool(now)` |
| **预期结果** | 返回裸 id 列表 ['hy3','hy4-preview']，元素不含 'custom-local:' 前缀；含 recommended_prefix 字段（程序项 ''） |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.2 — TC-POOL-002（SC3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-POOL-002 |
| **对应 Spec** | build_candidate_pool/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 扫描器产出程序侧 id 'hy3' |
| **输入** | 组装候选集 |
| **预期结果** | 不拼接 'custom-local:' 前缀；recommended_prefix='' |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.3 — TC-POOL-003（SC3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-POOL-003 |
| **对应 Spec** | build_candidate_pool/spec.md → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | 扫描器产出为空 |
| **输入** | 回退 `load_declared_models()` |
| **预期结果** | 返回 BYOK 裸 id，标注 source='byok_fallback'；调用方据此加 'custom-local:' 前缀 |
| **当前状态** | ❌ 测试缺 |

#### 案例 2.4 — TC-POOL-004（SC3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-POOL-004 |
| **对应 Spec** | build_candidate_pool/spec.md → Scenario: SC-004 |
| **优先级** | P1 |
| **预置条件** | 扫描器产出含 hy3 且 models.json 也声明同名 BYOK 'hy3' |
| **输入** | 组装候选集 |
| **预期结果** | 优先程序侧 hy3（裸 id），默认路线零 BYOK 项 |
| **当前状态** | ❌ 测试缺 |

### 功能 3：resolve_free_window / next

#### 案例 3.1 — TC-RFN-001（C3 / SC4）

| 字段 | 内容 |
|------|------|
| **ID** | TC-RFN-001 |
| **对应 Spec** | resolve_free_window_next/spec.md → Scenario: SC-001 |
| **优先级** | P0 |
| **预置条件** | 扫描器有免费模型；FREE_WINDOW_DEFAULT 仍含 until='2026-10-10' |
| **输入** | `resolve_source('auto')` |
| **预期结果** | 基于扫描器 free_now 决策（有→'all'）而非硬编码 until；返回带 scanner_reason |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.2 — TC-RFN-002（C3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-RFN-002 |
| **对应 Spec** | resolve_free_window_next/spec.md → Scenario: SC-002 |
| **优先级** | P0 |
| **预置条件** | 某 id 扫描器判定 free_now=True |
| **输入** | `is_free_window(model_id, now)` |
| **预期结果** | 优先返回扫描器判定；扫描器整体不可用时回落 models.json freeWindow 链 |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.3 — TC-RFN-003（C4 / SC3）

| 字段 | 内容 |
|------|------|
| **ID** | TC-RFN-003 |
| **对应 Spec** | resolve_free_window_next/spec.md → Scenario: SC-003 |
| **优先级** | P0 |
| **预置条件** | cmd_next 选中程序侧 'hy3' |
| **输入** | `cmd_next` 输出 |
| **预期结果** | 输出裸 id 'hy3'（不含 'custom-local:'）；recommended_prefix='' |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.4 — TC-RFN-004（C4）

| 字段 | 内容 |
|------|------|
| **ID** | TC-RFN-004 |
| **对应 Spec** | resolve_free_window_next/spec.md → Scenario: SC-004 |
| **优先级** | P0 |
| **预置条件** | cmd_next 选中 BYOK 兜底项（source='byok_fallback'） |
| **输入** | `cmd_next` 输出 |
| **预期结果** | recommended_prefix='custom-local:'；裸 id 本身不含前缀 |
| **当前状态** | ❌ 测试缺 |

#### 案例 3.5 — TC-RFN-005（SC4）

| 字段 | 内容 |
|------|------|
| **ID** | TC-RFN-005 |
| **对应 Spec** | resolve_free_window_next/spec.md → Scenario: SC-005 |
| **优先级** | P0 |
| **预置条件** | v5.5.0 变更已落地 |
| **输入** | 检查 SKILL.md 与 pick_model.py 源码 |
| **预期结果** | 不含 until='2026-10-10' 与统一 '23:00-08:00' 硬编码；`fstdd validate` 确认无残留 |
| **当前状态** | ❌ 测试缺 |

## 三、测试执行矩阵

| 功能模块 | 单元测试 | 集成测试 | E2E/文档 | 状态 |
|----------|---------|----------|----------|------|
| scan_program_config | TC-SCAN-001~006 | — | — | 🟡 待补 |
| build_candidate_pool | TC-POOL-001~004 | — | — | 🟡 待补 |
| resolve_free_window / next | TC-RFN-001~002 | TC-RFN-003~004 | TC-RFN-005 | 🟡 待补 |

## 四、回归风险矩阵

| 风险区域 | v5.5.0 改动 | 已有回归保护 | 风险等级 |
|----------|-------------|-------------|---------|
| `is_free_window` 调用方 | 改判据为消费扫描器 | test-doctor-command 现有断言须扩展 | 🔴 高（签名兼容须保持） |
| `resolve_source('auto')` 调用方 | 决策源切换 | 现有 auto 测试须扩展 | 🔴 高 |
| `cmd_next` 输出格式 | 新增 recommended_prefix 字段 | test-scheduler-contract 契约断言 | 🟡 中（新增字段非破坏） |
| SKILL.md 委派铁律 | 收窄 custom-local 前缀 | test-fmr-doc-sample 同步断言 | 🟡 中 |
| 现有硬编码默认值链路 | FREE_WINDOW_DEFAULT 移除/收窄 | 无直接测试 | 🟡 中（C5 回退须保） |

## 五、建议补充顺序

1. **第一优先（P0）**：TC-SCAN-001/002/004/005、TC-POOL-001/002/003、TC-RFN-001/002/003/004/005
2. **第二优先（P1）**：TC-SCAN-003/006、TC-POOL-004
3. **第三优先（后续）**：折扣中间态的更多边界（跨午夜 23:30 / 00:30 / 08:00 全覆盖）、多 promo 叠加

## 六、证据记录

| 证据 | observed_at（带时区） | observed_base_git_sha | 来源 |
|---|---|---|---|
| 双根 cache 字段实测：hy3 全天免费 / hy4 夜间免费 / glm-5.2 夜间0.5x / deepseek-v4 非高峰0.5x / validUntil=2026-11-01 / AI 根 deepseek-v4.1-flash base x0.00 | 2026-10-11T14:20:00+08:00 | 829fc03（用户上报 v5.4 HEAD，待复验） | 双根 acc-product-config-v3.json 直读实测（proposal.yaml evidence 段） |
| pick_model.py L109 FREE_WINDOW_DEFAULT.until='2026-10-10' 硬编码 | 2026-10-11T14:45:00+08:00 | 829fc03 | 源码 grep 实测 |
| SKILL.md L366 含 'until':'2026-10-10' 硬编码 | 2026-10-11T14:45:00+08:00 | 829fc03 | SKILL.md grep 实测（MEMORY 记载） |

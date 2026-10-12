# Spec: build_candidate_pool

> Change: relay-v550-program-cache-scanner | Auto-generated Human View

## Requirements

### Requirement: 候选池默认只用程序侧免费/折扣模型裸 id，不含 custom-local: 前缀。

#### Scenario: SC-001

- **GIVEN** 扫描器产出当前免费模型 [hy3, hy4-preview]（free_now=True）
- **WHEN** 调用 build_free_candidate_pool(now)
- **THEN** SHALL 返回裸 id 列表 ['hy3','hy4-preview']，元素不含 'custom-local:' 前缀
- **AND** 程序侧折扣模型（effective!=0）是否纳入由候选池配置决定，但 SHALL 同样用裸 id

#### Scenario: SC-002

- **GIVEN** 扫描器产出的模型 id 为程序侧平台模型（如 'hy3'）
- **WHEN** build_free_candidate_pool 组装候选集
- **THEN** SHALL 不拼接 'custom-local:' 前缀到程序侧 id
- **AND** 输出 JSON SHALL 含 recommended_prefix 字段，程序项为 ''（空）

### Requirement: BYOK custom-local:* 仅作兜底，默认路线不含 BYOK。

#### Scenario: SC-003

- **GIVEN** 扫描器产出为空（当前无任何免费模型）
- **WHEN** build_free_candidate_pool 回退到 load_declared_models()
- **THEN** SHALL 返回 BYOK 裸 id，并在结果中标注 source='byok_fallback'
- **AND** 调用方对 BYOK 兜底项 SHALL 加 'custom-local:' 前缀（与程序项区分）

#### Scenario: SC-004

- **GIVEN** 扫描器产出非空（含 hy3）且 models.json 中也声明了同名 BYOK 模型 'hy3'
- **WHEN** build_free_candidate_pool 组装候选集
- **THEN** SHALL 优先采用扫描器的程序侧 hy3（裸 id），不将 BYOK 同名项混入默认候选集
- **AND** 默认路线 SHALL 零 BYOK 项（BYOK 仅兜底触发）

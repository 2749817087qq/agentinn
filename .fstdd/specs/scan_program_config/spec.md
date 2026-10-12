# Spec: scan_program_config

> Change: relay-v550-program-cache-scanner | Auto-generated Human View

## Requirements

### Requirement: 扫描双根程序缓存，按 active promotion 计算 effective credits，输出当前免费/折扣模型清单（含时段、有效期、倍率）。

#### Scenario: SC-001

- **GIVEN** 双根缓存均存在且字段完整；now 落在 hy3 全天免费窗内、hy4-preview 夜间窗内
- **WHEN** 调用 scan_program_config(now=now)
- **THEN** SHALL 返回含 hy3(free_now=True, window=null, valid_until=2026-11-01) 与 hy4-preview(free_now=True, window={start:23,end:8}, valid_until=2026-11-01) 的条目
- **AND** 每条目 SHALL 含 base_credits / effective_credits / free_now / source_root
- **AND** effective_credits SHALL = base × active_promo_factor

#### Scenario: SC-002

- **GIVEN** 双根缓存均存在；某模型 id 在两根都存在但 effective 不同（如 AI 根 base x0.00 vs 另一根 base x0.29）
- **WHEN** scan_program_config 合并双根同 id 模型
- **THEN** SHALL 取更低 effective 作为合并结果（保守，避免把收费当免费）
- **AND** 合并后 source_root SHALL 标记来源，便于追溯

#### Scenario: SC-003

- **GIVEN** now 落在 glm-5.2 夜间折扣窗（effective = base × 0.5 ≠ 0）
- **WHEN** scan_program_config 处理折扣模型
- **THEN** 该模型 free_now SHALL = False（effective != 0 即非免费），但 SHALL 出现在折扣清单（effective_credits 反映 0.5x）
- **AND** free_now 严格判定 SHALL 为 effective_credits == 0

### Requirement: 缓存缺失/字段异常时降级，不静默返回空清单导致误判为'无免费'。

#### Scenario: SC-004

- **GIVEN** 仅一根缓存缺失、另一根正常
- **WHEN** scan_program_config 逐根读取
- **THEN** SHALL 跳过缺失根并记 warning，继续用正常根产出结果（非空）
- **AND** 结果 SHALL 携带 warnings[] 标记被跳过根

#### Scenario: SC-005

- **GIVEN** 双根均缺失或双根字段完全无法解析（扫描器整体不可用）
- **WHEN** scan_program_config 判定整体不可用
- **THEN** SHALL 显式告警并回退到既有 models.json freeWindow 链（不静默空清单）
- **AND** 若回退链本身也失败（如 models.json 缺失），SHALL 以非零退出码报错

#### Scenario: SC-006

- **GIVEN** 某根缓存存在但 models[] 中单条模型缺 credits 字段
- **WHEN** scan_program_config 解析该模型
- **THEN** SHALL 将该模型标记 degraded 并跳过，不中断整次扫描
- **AND** degraded 列表 SHALL 包含在返回结果中供上层告警

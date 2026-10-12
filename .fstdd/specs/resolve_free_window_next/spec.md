# Spec: resolve_free_window_next

> Change: relay-v550-program-cache-scanner | Auto-generated Human View

## Requirements

### Requirement: 免费窗口判定改为消费扫描器结果，移除对硬编码日期/时段的依赖。

#### Scenario: SC-001

- **GIVEN** 扫描器存在当前免费模型；FREE_WINDOW_DEFAULT 常量仍含 until='2026-10-10'
- **WHEN** resolve_source('auto') 决策 all/custom
- **THEN** SHALL 基于扫描器 free_now 结果决定（有免费→'all'），而非基于 FREE_WINDOW_DEFAULT 的硬编码 until
- **AND** resolve_source 返回值 SHALL 附带 scanner_reason 说明判定来源

#### Scenario: SC-002

- **GIVEN** 某程序模型 id 经扫描器判定 free_now=True
- **WHEN** is_free_window(model_id, now) 被调用
- **THEN** SHALL 优先返回扫描器判定 (True, '<scanner reason>')
- **AND** 扫描器整体不可用时，SHALL 回落既有 models.json freeWindow 链（C5 回退），不报错中断

### Requirement: relay next 输出程序模型裸 id，custom-local: 前缀仅保留给 BYOK 兜底路线。

#### Scenario: SC-003

- **GIVEN** cmd_next 选中程序侧模型 'hy3'
- **WHEN** cmd_next 输出 selected
- **THEN** SHALL 输出裸 id 'hy3'（不含 'custom-local:' 前缀）
- **AND** 输出 JSON SHALL 含 recommended_prefix=''（程序项）

#### Scenario: SC-004

- **GIVEN** cmd_next 选中 BYOK 兜底路线模型（source='byok_fallback'）
- **WHEN** cmd_next 输出 selected
- **THEN** SHALL 在 recommended_prefix 字段给出 'custom-local:'，调用方据此加前缀
- **AND** 裸 id 本身 SHALL 不含前缀（前缀由调用方按 recommended_prefix 拼接）

### Requirement: SKILL.md 硬编码 FREE_WINDOW_DEFAULT.until 与统一窗口判断被移除，且无残留常量。

#### Scenario: SC-005

- **GIVEN** v5.5.0 变更已落地
- **WHEN** 检查 SKILL.md 与 pick_model.py 源码
- **THEN** SHALL 不含 FREE_WINDOW_DEFAULT.until='2026-10-10' 与统一 '23:00-08:00' 硬编码窗口常量
- **AND** fstdd validate SHALL 能确认无残留硬编码日期/时段常量（SC4 可验证）

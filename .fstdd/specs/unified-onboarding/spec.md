# Spec: unified-onboarding

> 主规范（合并视图）。来源变更：
> - 2026-10-12-relay-v560-unified-onboarding（Auto-generated Human View）
> - 2026-10-12-relay-v561-agenthub-wiring（增量合并，2026-10-12）
>
> 说明：v5.6.1 增量需求在原 change 内使用 SC-011/SC-012（change 全局序号）；
> 合并入本 capability 时因 SC-011 已被占用，顺延重编为 **SC-012 / SC-013**（语义不变）。

## Requirements

### Requirement: onboard（读）一次性汇总统一向导数据：系统模型（含宿主时段·只读）+ 自定义/桥接模型（含扫描预填）+ AgentHub

#### Scenario: SC-001

- **GIVEN** 临时 HOME 下有 models.json（含平台模型 + 自定义/桥接模型）
- **WHEN** 执行 onboard（无参数，读）
- **THEN** SHALL 输出 JSON，含 system_models 数组（每条含宿主时段 start_hour/end_hour）、custom_models 数组、agenthub 对象
- **AND** system_models 每条 SHALL 标注只读（read_only=true 或等价字段）
- **AND** SHALL NOT 修改任何 state 或 models.json（只读命令）

#### Scenario: SC-002

- **GIVEN** 存在桥接模型（origins 识别为 qoder-free / ow-bridge）
- **WHEN** 执行 onboard（读）
- **THEN** SHALL 尝试扫描桥接模型的免费时段；扫到则 custom_models 对应条目的时段预填为扫描结果
- **AND** 桥接端点不可达时 SHALL 静默回落 all-day，不抛异常、不阻断向导
- **AND** 扫不到的纯 BYOK 模型 SHALL 默认 all-day

### Requirement: onboard set（写）落盘：仅自定义/桥接模型写 window 覆写 + free_allowlist + state.relay_onboard

#### Scenario: SC-003

- **GIVEN** 向导结果为 {groups, custom_periods, agenthub_pref}
- **WHEN** 执行 onboard set（带向导结果）
- **THEN** SHALL 对每个自定义/桥接模型写逐模型 window 覆写（_write_override_window，model_id=mid），并写 free_allowlist 与 state.relay_onboard
- **AND** state.relay_onboard SHALL 含 {confirmed_at, groups, custom_periods, agenthub_pref}
- **AND** all_day 模型 SHALL 写 {start_hour:0,end_hour:0}（恒真语义）

#### Scenario: SC-004

- **GIVEN** 向导结果中包含系统模型（_source=platform）
- **WHEN** 执行 onboard set
- **THEN** SHALL NOT 为系统模型写 window 覆写（宿主程序规范为准）
- **AND** 系统模型的时段写入 SHALL 被跳过，且不报错

### Requirement: onboard-status 的 due 判定 = 未确认 或 跨自然日 或 数据漂移

#### Scenario: SC-005

- **GIVEN** state.relay_onboard 缺失（从未确认）
- **WHEN** 执行 onboard-status
- **THEN** SHALL 返回 due=true，confirmed_at=null

#### Scenario: SC-006

- **GIVEN** relay_onboard.confirmed_at 为今天本地自然日，且 last_config_hash == 当前配置 hash
- **WHEN** 执行 onboard-status（now 注入为当天）
- **THEN** SHALL 返回 due=false，drift_detected=false

#### Scenario: SC-007

- **GIVEN** relay_onboard.confirmed_at 为昨天本地自然日
- **WHEN** 执行 onboard-status（now 注入为今天）
- **THEN** SHALL 返回 due=true

#### Scenario: SC-008

- **GIVEN** relay_onboard.confirmed_at 为今天，但 last_config_hash != 当前配置 hash（如新增免费模型）
- **WHEN** 执行 onboard-status
- **THEN** SHALL 返回 due=true，drift_detected=true

### Requirement: next / inventory 透传 onboard_due 布尔

#### Scenario: SC-009

- **GIVEN** relay_onboard 未确认（due=true）
- **WHEN** 执行 next 或 inventory
- **THEN** 输出 JSON SHALL 含 onboard_due=true
- **AND** relay_onboard 已确认当天且同 hash 时 SHALL 为 false

### Requirement: 存量迁移：free_allowlist + 自定义模型 window 覆写 → relay_onboard，旧键保留只读

#### Scenario: SC-010

- **GIVEN** 存量 state 含 free_allowlist={ids} 与某自定义模型的 window 覆写
- **WHEN** 执行 onboard（读）或 onboard-status（触发迁移派生）
- **THEN** SHALL 派生出 relay_onboard.groups（按扫描器分类）与 custom_periods
- **AND** free_allowlist 旧键 SHALL 保留（只读，不删除）
- **AND** 脏数据（confirmed_at 缺失/ids 非法）SHALL 降级为空但不报错

### Requirement: AgentHub 双层：偏好与开通完成态分离存储

#### Scenario: SC-011

- **GIVEN** 向导中 AgentHub 偏好 toggle = 开
- **WHEN** 执行 onboard set
- **THEN** SHALL 写 state.relay_onboard.agenthub_pref=true
- **AND** SHALL NOT 因偏好为真就写 agenthub_onboarded=true（开通完成态只由 multihub-node-onboarding 写）

### Requirement: onboard-status / onboard 的 agenthub 对象扩展（只增字段，不改既有 pref/onboarded 语义）

#### Scenario: SC-012

- **GIVEN** 任意 state（含或不含 relay_onboard）
- **WHEN** 执行 onboard-status
- **THEN** agenthub 对象 SHALL 含 pref / onboarded / action / prompted_on 四键
- **AND** pref / onboarded 的取值语义 SHALL 与改动前逐字一致（SC-011 原语义不变）
- **AND** action / prompted_on 为新增键，缺省分别为 "none" / null

### Requirement: onboard set（写）保留既有 agenthub_prompted_on，避免重跑向导清空当日防打扰记录

#### Scenario: SC-013

- **GIVEN** state.relay_onboard.agenthub_prompted_on 已为今天；随后执行 onboard set（agenthub_pref=true）
- **WHEN** 读回 state.relay_onboard
- **THEN** agenthub_prompted_on SHALL 仍为今天（未被清空）
- **AND** confirmed_at / last_config_hash SHALL 按本次 set 更新（其余字段正常刷新）

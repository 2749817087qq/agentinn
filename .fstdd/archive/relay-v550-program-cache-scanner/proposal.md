# free-model-relay v5.5.0：启动扫描程序侧账号-产品配置缓存，替代硬编码免费窗口

<!-- source_hash: 546850bc4f9e0ad5 -->
<!-- generated_at: 2026-10-11T06:45:53+00:00 -->
<!-- canonical: canonical/proposals/relay-v550-program-cache-scanner.yaml -->

## Why

SKILL.md 硬编码了 `FREE_WINDOW_DEFAULT.until="2026-10-10"` 与统一 23:00–08:00 免费窗口， 带来三重错误：(1) 错误排除本应免费的 hy3 系——实测 hy3/hy3-b/hy3-c 是全天免费（base credits x0.00，无时段限制）； (2) 误判"平台活动已结束"——实测活动实际至 2026-11-01；(3) 任何平台活动变化都需人工改 skill 才能跟随，且容易静默出错。


## What Changes

- 新增启动扫描器 scan_program_config()：读取双根 acc-product-config-v3.json，解析 models[].credits 与 modelPromotions[] 的 schedule（时段）+ validUntil（有效期）+ discountedCredits（折扣后倍率）， 按"当前时刻是否在活动时段内且未过期"计算 effective = base_credits × active_promo_factor， 输出"当前免费/折扣模型清单（含时段/有效期/倍率）"。

- 重写候选池构建逻辑 build_candidate_pool()：默认只用程序侧免费/折扣模型（裸 id：hy3 / hy4-preview / glm-5.2 / deepseek-v4 系）， BYOK custom-local:* 退出默认路径，仅作兜底路线。

- 移除 SKILL.md 中硬编码的 FREE_WINDOW_DEFAULT.until="2026-10-10" 与统一 23:00–08:00 窗口判断， 改为消费扫描器输出（free_now = scanner.effective == 0 且当前在窗口内）。

- 重写 relay next 输出：程序模型用裸 id（hy3 等），不再强制 custom-local: 前缀； 该前缀仅保留给 BYOK 兜底路线（应对同名劫持 + 429 限流两个坑只对 BYOK 路线存在）。

- 缓存降级处理：缓存文件未生成 / 路径变更 / 字段缺失 / 已过期时，回退到 models.json 或显式报错，不静默返回空清单导致误判为"无免费"。


### New Capabilities

- **scan_program_config**：从程序侧账号-产品配置缓存动态生成当前免费/折扣模型清单（含时段、有效期、倍率），零 API key、零硬编码。

### Modified Capabilities

- **build_candidate_pool**：候选池默认只用程序侧免费/折扣模型裸 id；BYOK custom-local:* 仅作兜底。
- **resolve_free_window / next**：免费窗口判定与 next 输出改为消费扫描器结果，不再依赖 skill 硬编码日期与时段。

## Success Criteria

- [ ] SC1：扫描器能从双根缓存读取并输出当前免费模型清单，且 hy3 标记为全天免费（base credits x0.00、无时段限制）、hy4-preview 标记为夜间免费（23:00–08:00）、validUntil=2026-11-01。
- [ ] SC2：当 acc-product-config-v3.json 缺失或字段异常时，扫描器回退到 models.json 或显式报错（非零退出），不静默返回空清单导致误判为'无免费'。
- [ ] SC3：候选池默认只含程序侧免费/折扣模型裸 id；relay next 输出不含 custom-local: 前缀（除非走 BYOK 兜底路线）。
- [ ] SC4：SKILL.md 中 FREE_WINDOW_DEFAULT.until="2026-10-10" 与统一 23:00–08:00 判断被移除，且 fstdd validate 能确认无残留硬编码日期/时段常量。
- [ ] SC5：在 2026-10-11 实测活动窗口内，扫描器输出的免费清单与程序缓存逐项一致（hy3 全天免费、hy4 夜间免费、glm-5.2 夜间5折、deepseek-v4 非高峰5折）。
- [ ] SC6：双根（WorkBuddy + WorkBuddy AI）缓存均被扫描并合并，AI 根额外标记 deepseek-v4.1-flash base 0x 免费也被纳入候选池。

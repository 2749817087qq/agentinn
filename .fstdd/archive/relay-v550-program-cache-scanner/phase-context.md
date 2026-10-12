# Phase Context — relay-v550-program-cache-scanner

> Change: v5.5.0 程序侧缓存扫描器
> 模式：standard（复杂度评分 7）
> 当前阶段：Phase 2 SPEC（Gate 2 已确认，2026-10-11T15:23 +08:00）

## Phase 1（已完成，待续）
- 提案已锁定：`.fstdd/canonical/proposals/relay-v550-program-cache-scanner.yaml`
- 5 项 what_changes（C1 扫描器 / C2 候选池 / C3 移除硬编码 / C4 next 裸 id / C5 降级）
- 6 条 Success Criteria（SC1–SC6）

## Phase 2（本阶段，已锁定）

### 关键设计决策（design.md，5 Decision）
1. **新增 `scan_program_config(roots, now)`**：双根（`~/.workbuddy/cache` + `~/.workbuddy-ai/cache`）读 `acc-product-config-v3.json`；`effective = base × active_promo_factor`；输出 `{id, base_credits, effective_credits, free_now, window, valid_until, source_root}`；同 id 取更低 effective。
2. **`build_free_candidate_pool()`**：默认候选集 = 扫描器 `free_now` 裸 id；BYOK 仅兜底（标 `source='byok_fallback'`）。
3. **移除硬编码**：`FREE_WINDOW_DEFAULT.until` / 统一 23:00–08:00 删除；`resolve_source('auto')` 改消费扫描器；`is_free_window` 优先用扫描器、不可用时回落 models.json。
4. **next 裸 id**：程序模型输出裸 id；`custom-local:` 前缀仅 BYOK 兜底（`recommended_prefix` 字段区分）。
5. **两级降级**：单根异常→跳过+warning；双根全失败→回退 models.json freeWindow，再失败则非零退出。**不变量：任何路径不得静默空清单**。

### 设计依据关键事实（实测，2026-10-11T14:20 +08:00）
- hy3/hy3-b/hy3-c 全天免费（base x0.00）；hy4-preview/-dev 夜间 23:00–08:00 免费；glm-5.2 夜间 0.50x；deepseek-v4 非高峰 0.50x；AI 根 deepseek-v4.1-flash base x0.00。
- 全部 7 条 promo `validUntil=2026-11-01`。
- 真实插入点（grep 核实）：`cmd_next` L1742 / `resolve_source` L1379 / `is_free_window` L473 / `load_declared_models` L1303 / `FREE_WINDOW_DEFAULT` L109。

### 规格与测试覆盖
- 3 个 code spec（scan_program_config / build_candidate_pool / resolve_free_window_next）+ 3 个 agent spec。
- 8 Requirement / 15 Scenario；15 TC（TC-SCAN-001~006 / TC-POOL-001~004 / TC-RFN-001~005）覆盖 SC1–SC6。
- `fstdd validate`：0 error。

### 已知坑点（Phase 3 须留意）
- **签名兼容**：`is_free_window(model_id, now)` 位置参数兼容（SC-FWX-009/010）须保持，第一参数非 str 时按 now 处理——Phase 3 改判据时不得破坏。
- **`custom-local:` 收窄**仅改 SKILL.md 委派约定 + `next` 的 `recommended_prefix`；产品既有裸 id 输出不破坏。
- **SKILL.md 同步**：SC4 要求移除 L366 `"until":"2026-10-10"`，须同步三处载荷（install.sh / 镜像根 / verify_payload）。
- **跨午夜时段**：23:00–08:00 边界（23:30 / 00:30 / 08:00）须单测覆盖。
- **双根同 id**：合并取更低 effective，避免把收费当免费。

### 经验交叉检查
- 本仓库 `.fstdd/experiences` 为空（刚 init）→ 无经验注入；沿用 Phase 1 实测事实。

### 待冒烟假设（交付后真人验证）
- H-1：扫描器字段解析对真实缓存逐条一致（含 AI 根 deepseek-v4.1-flash）。
- H-2：`next` 裸 id 委派不触同名劫持（程序路线已无 custom-local 前缀）。
- H-3：双根任一缺失时降级 warning 不静默空清单。

## 下一步
- Phase 3 BUILD：按 `build_candidate_pool` / `scan_program_config` / `resolve_free_window_next` 三 capability 切切片，RED→GREEN→REFACTOR，每切片跑回归 + B3.4 记录。
- 注意本环境 git 解析不一致（v5.4 tag 落点待 Deliver 复验）。

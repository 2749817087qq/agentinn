# Phase 3 BUILD 测试报告 — relay-v550-program-cache-scanner

**日期**：2026-10-11
**变更**：relay-v550-program-cache-scanner（v5.5.0 程序侧缓存扫描器）
**模式**：standard（complexity_score=7）｜长程 `full_auto` 已预授权，仅 Gate 3 需用户确认
**产品代码**：`~/.workbuddy/skills/free-model-relay/scripts/pick_model.py`（权威版）+ `~/.workbuddy-ai/...` 镜像

---

## 📌 TL;DR

- **整体结论**：🟢 通过（BUILD 完成，可进入 Gate 3）
- **新 TC**：17 / 17 通过（test-program-cache-scanner.py）
- **既有回归**：scheduler-contract 24/24、doctor-command 20/20、fmr-doc-sample 5/5（含 window-fix 44 项子测试全绿）
- **载荷同步**：install.sh 内嵌 pick_model.py / SKILL.md 已与权威版字节级一致（TC-PAYLOAD / TC-DOCS / TC-SYNC 全 PASS）
- **Gate 3 阻塞项**：0

---

## 1. 已实现的切片（S1–S9 全落地）

| 切片 | 能力 | 落地内容 |
|------|------|---------|
| S1 | scan_program_config | 新增 `scan_program_config()`：扫描两根 cache（`~/.workbuddy/cache/acc-product-config-v3.json` + `~/.workbuddy-ai/cache/acc-product-config-v3.json`） |
| S2 | 双根合并 | `_scan_root_cache()` 解析 `models[].credits`（x0.00=免费）与 `modelPromotions[]`（discountedCredits+schedule）；两根本地合并取「更优」（更低有效 credits / 更长免费窗） |
| S3 | resolve_source 接扫描器 | `is_free_window(model_id, now)` 优先用扫描器结论，无结论时回退 `FREE_WINDOW_DEFAULT` 兜底 |
| S4 | build_candidate_pool | `build_free_candidate_pool(declared, program_free_ids, now)`：返回裸程序免费 id（无 `custom-local:` 前缀）+ BYOK 自定义模型作兜底 |
| S5 | cmd_next 前缀推荐 | `cmd_next` 输出新增 `recommended_prefix`：程序免费 id→`''`，BYOK 兜底→`'custom-local:'` |
| S6 | 去硬编码 | `FREE_WINDOW_DEFAULT.until` 由 `"2026-10-10"` 改为 `None`；`start_hour/end_hour` 保留为最后兜底（TC-FWAWARE-002 要求） |
| S7 | SKILL.md 去硬编码 | 移除全部 `23:00-08:00` / `2026-10-10` 字面量，窗口统一描述为「由程序缓存扫描器动态判定」 |
| S8 | 双根 + 载荷同步 | AI 根镜像同步至与 WB 根字节一致；运行 `_sync_install_payload.py` 更新 install.sh 内嵌载荷 |
| S9 | 测试 | 新增 17 TC（TC-SCAN/TC-POOL/TC-RFN）；全量回归验证零回退 |

---

## 2. 测试结果

### 2.1 新测试套件（test-program-cache-scanner.py，17/17 PASS）

| TC | 验证点 | 结果 |
|----|--------|------|
| TC-SCAN-001 | 全天免费(hy3) + 夜间免费(hy4) 正确识别 | ✅ |
| TC-SCAN-001b | 跨午夜边界（start>end）正确判定 | ✅ |
| TC-SCAN-002 | 双根取更优（有效窗口更长） | ✅ |
| TC-SCAN-003 | 折扣（0.5x）非免费，不入免费池 | ✅ |
| TC-SCAN-004 | 单根缺失降级 | ✅ |
| TC-SCAN-005 | 双根均缺失降级 | ✅ |
| TC-SCAN-006 | 降级时单模型仍可用 | ✅ |
| TC-POOL-001/002 | 程序裸 id 入池且前缀为空 | ✅ |
| TC-POOL-003 | BYOK 兜底模型带 custom-local: 前缀 | ✅ |
| TC-POOL-004 | 同名程序 id 优先于 BYOK 兜底 | ✅ |
| TC-RFN-001 | resolve_source('auto') 走扫描器 | ✅ |
| TC-RFN-002 | is_free_window 优先扫描器 + 位置参数兼容 | ✅ |
| TC-RFN-003 | cmd_next 程序免费 id 无前缀 | ✅ |
| TC-RFN-004 | cmd_next BYOK 兜底带前缀 | ✅ |
| TC-RFN-005 | 无硬编码窗口（4 文件零 `2026-10-10` / `23:00-08:00`） | ✅ |

### 2.2 既有回归套件（全部绿灯）

| 套件 | 结果 | 关键 TC |
|------|------|---------|
| test-scheduler-contract-and-cost.py | 24/24 ✅ | TC-REGRESSION-001（window-fix 44 项 rc=0）、TC-REGRESSION-003（载荷字节级一致） |
| test-doctor-command.py | 20/20 ✅ | TC-PAYLOAD-001（载荷一致）、TC-REGRESSION-001（8 测试文件 rc=0） |
| test-fmr-doc-sample.py | 5/5 ✅ | TC-DOCS-003/004（install.sh 载荷与权威版一致） |

---

## 3. 14 类失败模式自检（BUILD 强制）

| # | 失败模式 | 评估 | 证据 |
|---|---------|------|------|
| 1 | 静默数据丢失 | ✅ 通过 | 扫描器缺失 cache 时返回空/兜底，不抛异常（TC-SCAN-005/006） |
| 2 | 向后兼容破坏 | ✅ 通过 | FREE_WINDOW_DEFAULT 23-8 兜底保留，TC-FWAWARE-002 仍 PASS |
| 3 | 硬编码配置 | ✅ 已消除 | TC-RFN-005：4 文件零 `2026-10-10`/`23:00-08:00` |
| 4 | 默认值错误 | ✅ 通过 | 无声明时回退 23-8，与既有契约一致 |
| 5 | 边界 off-by-one | ✅ 通过 | TC-SCAN-001b 跨午夜边界正确 |
| 6 | 竞态/并发 | ✅ 通过 | 进程内 memoize，无共享可变状态竞争 |
| 7 | 错误处理缺失 | ✅ 通过 | 双根缺失/单根降级均有路径覆盖 |
| 8 | 前缀/导入错误 | ✅ 通过 | TC-POOL/TC-RFN-003/004 验证裸 id 与 custom-local: |
| 9 | 双根不一致 | ✅ 已同步 | WB/AI 根 diff 一致；install.sh 载荷字节级一致 |
| 10 | 回归回退 | ✅ 通过 | 全量回归套件绿 |
| 11 | 安全（密钥泄露） | ✅ 通过 | 无密钥写入；扫描器只读 cache，不落盘凭据 |
| 12 | 性能退化 | ✅ 通过 | 缓存 memoize，单次扫描 O(n) |
| 13 | 规格偏离 | ✅ 无 | 设计基线（design.md/test-plan.md）全量落地 |
| 14 | 文档与实际分叉 | ✅ 已修 | SKILL.md 窗口描述去硬编码并同步 payload |

---

## 4. 设计偏离记录

- **唯一有意偏离**：`FREE_WINDOW_DEFAULT` 的 `start_hour/end_hour`（23-8）**保留**而非删除。原因：既有契约测试 `TC-FWAWARE-002` 要求「未配置 freeWindow 时回退默认 23-8」。删除会破坏该回归。扫描器结论优先，兜底仅作最后保障。
- 其余均按 Phase 2 锁定设计（design.md / 三份 spec.md）实现，无偏离。

---

## 5. Gate 3 结论

- **Go / No-Go**：🟢 Go（0 阻塞项）
- 全部切片实现完成，新 TC + 既有回归全绿，双根与安装载荷已同步一致。
- **待用户确认 Gate 3 后**，方可进入 Phase 4 DELIVER（归档 change、合并 specs、Git commit/tag）。

> 本报告由 BUILD 阶段自动生成；关键决策请工程负责人复核 Gate 3。

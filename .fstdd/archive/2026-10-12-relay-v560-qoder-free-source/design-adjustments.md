# 设计调整说明 — relay-v560-qoder-free-source

> 原始设计基线：Phase 2 产出的 design.md + canonical/specs/*.yaml + test-plan.md
> 调整来源：Phase 3 (BUILD) 实现过程中的发现

## 调整汇总

| # | 调整类型 | 涉及文档 | 严重程度 | 调整阶段 | 影响 TC | 用户已知 |
|---|---------|---------|---------|---------|---------|---------|
| 1 | 配置覆盖通道降级 | design.md (D5) | Minor | Phase 3 | TC-QF-008 | 是（本文件） |
| 2 | 冷路径挂载点收窄 | design.md (D2) | Minor | Phase 3 | TC-QF-006/009 | 是（本文件） |
| 3 | 持久化助手替换（自建 `_safe_persist_qoder_free`） | design.md (D1) | Minor | Phase 3 | TC-QF-001/002/007 | 是（本文件） |

## 调整详细说明

### 调整 1: `qoder_free.config_path` 文件内配置键覆盖通道未实现（Minor）

- **原始设计**: design.md D5 规定 config 路径「可被环境变量 `QODER_FREE_CONFIG` **或 relay 配置键
  `qoder_free.config_path`** 覆盖」。
- **调整内容**: 仅实现**环境变量** `QODER_FREE_CONFIG` 覆盖；relay 内置配置文件键
  `qoder_free.config_path` 的读取通道**未实现**（已在 `resolve_qoder_free_config_path()`
  docstring 中显式注明「暂未实现，统一走环境变量」）。
- **调整原因**: 本机 relay 的配置覆盖纪律一贯走 `FMR_*` / 专用环境变量（v5.5.0 既有多处同构）；
  为单一 config 路径引入一套「文件内配置键」读取逻辑，收益（便携性）远小于成本（新增解析面 +
  与既有覆盖纪律不一致）。SC-004/SC-007 只要求「可被覆盖」且给出了 `QODER_FREE_CONFIG` 一条路径，
  环境变量通道**已满足规格**。
- **影响范围**: `scripts/pick_model.py` → `resolve_qoder_free_config_path`。
- **影响 TC**: TC-QF-008（`QODER_FREE_CONFIG` 覆盖生效，已绿）。
- **调整阶段**: Phase 3 (BUILD, Slice S2)
- **用户已知**: 是（本文件）

### 调整 2: 自动发现冷路径挂载点收窄为 `cmd_scan` + `cmd_next`（Minor）

- **原始设计**: design.md D2 表述为「`cmd_scan` … / `cmd_next` / `cmd_inventory` 入口」三处挂载。
- **调整内容**: 实际仅在 `cmd_scan`（L1874）与 `cmd_next`（L2179）挂载 `maybe_discover_qoder_free()`；
  `cmd_inventory` **未挂载**。
- **调整原因**: 行为规格中**没有**任何 SC 要求 `inventory` 触发发现（SC-005 只约束 `next`、
  SC-006 只约束 `scan`）。`inventory` 是低频只读枚举命令，且在 Agent 向导流程中通常**先于**
  `next` 调用——此时若未发现，`inventory` 会以「无 qoder-free 条目」呈现（用户可在弹窗后由
  `next`/`scan` 补齐）。为避免在只读命令上引入联网副作用、并缩小对既有 `test-*`（会捕获
  inventory 输出）的影响面，**有意收窄**挂载点。
- **影响范围**: `scripts/pick_model.py` → `cmd_scan` / `cmd_next`（`cmd_inventory` 不挂载）。
- **影响 TC**: TC-QF-006（`next` TTL）/ TC-QF-009（`scan` 触发）—— 均绿。
- **调整阶段**: Phase 3 (BUILD, Slice S3)
- **用户已知**: 是（本文件）

### 调整 3: 持久化改自建 `_safe_persist_qoder_free`，不复用 `_write_models_json_entries`（Minor）

- **原始设计**: design.md D1 表述为「写入复用 `models add` 的 `_append_model_entry` +
  `_write_models_json_entries`（原子写 + 备份 + 锁）」。
- **调整内容**: 新增**专用** `_safe_persist_qoder_free(before, new_data)`：备份 + `_atomic_write_json`
  + 写后校验「**所有非 qoder-free 条目逐字不变（含 apiKey）**」，失败回滚并返回 `(backup, err)`，
  **不**调 `_cli_fail`。仍复用底层 `_atomic_write_json`（L1736）。
- **调整原因**: 实现时核对既有 `_write_models_json_entries`（L3794）发现两点**硬冲突**：
  1. 其备份失败分支直接 `_cli_fail(...)` ⇒ **非零退出 + stderr 输出**，与 D6「发现失败一律静默、
     绝不阻断 relay 流程」直接矛盾；
  2. 其比对基准是**单一 `target_id`**（`_strip_target(before, target_id)`），而 discover 一次
     可能写入**多个** qoder-free id，无法表达「保留所有非 qoder-free 条目」的校验语义。
  故自建一个「多条目 + 无 `_cli_fail` + 完整性校验」的持久化路径；**未**引入新的原子写实现
  （仍用 `_atomic_write_json`），也未改动 `models add` 既有写入函数（零回归面）。
- **影响范围**: `scripts/pick_model.py` → 新增 `_safe_persist_qoder_free`；既有写入函数**未改**。
- **影响 TC**: TC-QF-001（写入字段）/ TC-QF-002（失败不写）/ TC-QF-007（幂等 + 不覆盖他人）。
- **调整阶段**: Phase 3 (BUILD, Slice S2)
- **用户已知**: 是（本文件）

## 无偏离但已实测的关键约束

### SC9（cn:/global: 区域前缀 id 精确命中）

- design.md D7 把「若平台拒绝冒号 id ⇒ 可逆 sanitize + 还原」列为 Phase 3 实测验证项。
- **实测结论**: 主路径（id **原样保留**区域前缀）已通过 TC-QF-004 验证 —— 临时 HOME 写入
  `cn:qoder-free-x` 条目后，`next` 返回 `custom-local:cn:qoder-free-x`，`recommended_prefix`
  为 `custom-local:`。**未**触发平台拒绝，故 sanitize 兜底方案**未启用**（保留为设计中的
  条件性后备，不落地代码，避免引入未经验证的可逆变换）。
- **影响 TC**: TC-QF-004（已绿）。

# v5.6.0-qoder-free-source 切片执行计划

## Dependency Graph Summary

```
                    ┌────────────────────────────────────────┐
                    │ S1 来源归类内核 (D3 / C2)                │
                    │ KNOWN_EXTERNAL_OWNERS += qoderFreeOwner  │
                    │ OWNER_TOOL_MAP / _detect_source_tool     │
                    │ cmd_origins free_semantics               │
                    └───────────────────┬────────────────────┘
                                        │ 零依赖先行（不改池逻辑，仅归因）
                                        ▼
                    ┌────────────────────────────────────────┐
                    │ S2 discover 核心 (D1 / C1)               │
                    │ resolve_config_path / resolve_base       │
                    │ _probe_qoder_free_models                 │
                    │ _safe_persist_qoder_free（原子+校验）     │
                    │ discover_qoder_free（幂等/失败静默）      │
                    └───────────────────┬────────────────────┘
                                        │ S2 提供 discover_qoder_free
                    ┌───────────────────┼───────────────────┐
                    ▼                                       ▼
        ┌───────────────────────┐               ┌───────────────────────┐
        │ S3 TTL 自动触发 (D2/C1) │               │ S4 子命令 sync/status  │
        │ _touch_..._discovery    │               │ cmd_qoder_free         │
        │ maybe_discover（TTL+闸）│               │ CLI 注册               │
        │ scan/next 冷路径挂载    │               │ (D2)                   │
        └───────────┬───────────┘               └───────────┬───────────┘
                    └───────────────┬───────────────────────┘
                                    │ 发现链打通后，池/泄漏才有对象可验证
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        ┌───────────────────────┐       ┌───────────────────────┐
        │ S5 默认进池 (D4 / C3)  │       │ S6 零泄漏守门 (C4)     │
        │ vendor=Custom ⇒ 候选池 │       │ list/inventory/profile │
        │ custom-local: 前缀     │       │ /origins 无 apiKey 明文│
        └───────────┬───────────┘       └───────────┬───────────┘
                    └───────────────┬───────────────┘
                                    ▼
                    ┌────────────────────────────────────────┐
                    │ S7 回归同步                             │
                    │ 测试套件 + 载荷同步 + 全量回归          │
                    └────────────────────────────────────────┘
```

**并行化说明**：
- 并行组 1：**S1**（零依赖；仅改归因，不触碰发现/池逻辑，可先行落地）
- 并行组 2：**S2**（依赖 S1 的 `OWNER_TOOL_MAP` 口径；discover 写入的条目 owner 标记需与归因一致）
- 并行组 3：**S3 / S4**（均依赖 S2 的 `discover_qoder_free`；同改 `pick_model.py` 单文件 ⇒ 实际按序落盘以免编辑冲突）
- 并行组 4：**S5 / S6**（依赖 S2–S4 的发现链；二者只验证池/泄漏行为，不改核心逻辑）
- 并行组 5：**S7**（依赖 S1–S6，最后收口）

## Slice Execution Plan

| # | 优先级 | 风险 | 预估工时 | 并行组 | TC 覆盖 | 实现目标 | 依赖 |
|---|--------|------|---------|--------|---------|---------|------|
| 1 | P0 | 🟢 Low | S | 组1 | TC-QF-003 | `KNOWN_EXTERNAL_OWNERS` + `OWNER_TOOL_MAP` + `_detect_source_tool` 按标记派 tool + `cmd_origins` free_semantics | 无 |
| 2 | P0 | 🟡 Med | L | 组2 | TC-QF-001,002,007,008 | `resolve_qoder_free_config_path` / `resolve_qoder_free_base` / `_probe_qoder_free_models` / `_safe_persist_qoder_free` / `discover_qoder_free` | 1 |
| 3 | P0 | 🟡 Med | M | 组3 | TC-QF-006,009 | `_touch_qoder_free_discovery` + `maybe_discover_qoder_free`（TTL+FMR_QF_AUTODISCOVER 闸）+ `cmd_scan`/`cmd_next` 挂载 | 2 |
| 4 | P1 | 🟢 Low | S | 组3 | （TC-QF-001 sync 路径） | `cmd_qoder_free`（sync 强刷 / status 排障）+ 子命令注册 | 2 |
| 5 | P0 | 🟢 Low | S | 组4 | TC-QF-004 | 验证 vendor=Custom 天然进候选池 + `custom-local:` 前缀（无需 allowlist） | 2,3,4 |
| 6 | P0 | 🟢 Low | S | 组4 | TC-QF-005 | 验证 list/inventory/profile/origins 输出零 apiKey 明文 | 2,3,4 |
| 7 | P0 | 🟡 Med | M | 组5 | 全量 | `tests/test-relay-qoder-free-source.py`（19 断言）+ 载荷同步 + 全量回归 | 1-6 |

## Rationale

### Slice 1: 来源归类内核（P0，先行）
- **依赖关系**：S2 写入的条目带 `qoderFreeOwner` 标记，其归因口径由本切片定义；先落归因可让
  S2 的写入字段与 S6 的泄漏断言共用同一 `OWNER_TOOL_MAP`。
- **风险分析**：🟢 Low。改动面仅 `KNOWN_EXTERNAL_OWNERS` / `OWNER_TOOL_MAP` / `_detect_source_tool`
  一处分支 + `cmd_origins` 一处 `free_semantics` 分支；`qoderFreeOwner` 以 `Owner` 结尾，
  天然被既有 `_owner_marker_keys` 后缀判定捕获（REQ-MO-008），不破坏 relay/ow-bridge 既有分类。
  经验库匹配：EXP-2026-0003（`'stdd guard'` 假阴性）—— 同属「子串/后缀判据」坑，故本切片
  严格复用 `endswith("Owner")`，不新起判据。

### Slice 2: discover 核心（P0）
- **依赖关系**：S3/S4 均调用 `discover_qoder_free`；S5/S6 依赖其写入结果。
- **风险分析**：🟡 Med。I/O + 网络（可注入 `_probe` 离线单测）；写入走 `_safe_persist_qoder_free`
  的「备份 + 原子写 + 非 qoder-free 条目逐字不变」三重校验（保护既有条目 apiKey 完整性）。
  失败分支（config 缺失 / 不可达 / 空 / 持久化失败）一律 `ok=False` 静默返回（D6 零阻断）。

### Slice 3: TTL 自动触发（P0）
- **依赖关系**：消费 S2；为 S5/S6 提供「发现已自动发生」的前置。
- **风险分析**：🟡 Med。挂载在 `cmd_scan`（L1874）/ `cmd_next`（L2179）冷路径；
  由 `FMR_QF_AUTODISCOVER` 安全闸（默认启用）保护——既有测试套件若断言输出，可设 `=0` 关闭，
  避免对真实 `models.json` 的意外改写。经验库匹配：EXP-2026-0006（ASCII 断言）/ 现有 `next`
  输出契约用例，故 `maybe_discover_qoder_free` 全程吞异常、不刷 stdout。

### Slice 4: 子命令 sync/status（P1）
- **依赖关系**：消费 S2 的 `discover_qoder_free(force=True)`。
- **风险分析**：🟢 Low。纯 CLI 包装；`sync` 无视 TTL 强刷、`status` 出可达性/模型数/上次探测时刻。

### Slice 5 / 6: 默认进池 + 零泄漏（P0）
- **依赖关系**：依赖 S2–S4 的发现链。
- **风险分析**：🟢 Low。二者**不改核心逻辑**，仅以集成用例验证既有行为：
  `vendor=Custom ⇒ _source="custom"` 天然进池（`load_declared_models` 预勾 `default_free=True`）；
  所有对外输出经 `_mask_secret` 遮蔽（INT-005 / SC-MO-012 守门）。

### Slice 7: 回归同步（P0）
- **依赖关系**：全部。
- **风险分析**：🟡 Med。既有 `test-relay-source-governance.py`（origins 归因）/ scheduler 用例
  可能因新分支/新挂载变红；以 `tests/run-all.py` 全量回归确认零回归（见 test-report.md）。

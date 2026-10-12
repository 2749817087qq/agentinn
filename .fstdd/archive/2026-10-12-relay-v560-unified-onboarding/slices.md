# v5.6.0-unified-onboarding 切片执行计划

## Dependency Graph Summary

```
                    ┌──────────────────────────────────────┐
                    │ S1 纯函数内核                          │
                    │ _classify_onboard_models / _config_hash│
                    │ _onboard_due / migrate_to_relay_onboard│
                    └───────────────┬──────────────────────┘
                                    │ 全部依赖 S1（共享分类 + due + 迁移）
        ┌───────────────┬───────────┼───────────┬───────────────┐
        ▼               ▼           ▼           ▼
   ┌─────────┐    ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ S2 onboard│   │ S3 onboard│ │ S4 onboard│ │ S5 next/ │
   │  (读)     │   │ set (写)  │ │ -status   │ │ inventory│
   │ 汇总+桥接 │   │ 逐模型写  │ │  due 命令 │ │  透传    │
   └────┬────┘    └────┬─────┘ └────┬─────┘ └────┬─────┘
        └──────────────┴────────────┴────────────┘
                                    │ 命令面齐备后文档才有对象可写
                                    ▼
                          ┌───────────────────┐
                          │ S6 C1 文档          │
                          │ SKILL.md 新向导块   │
                          │ + 旧 wheel fallback │
                          │ + relay_instruction │
                          └─────────┬─────────┘
                                    ▼
                          ┌───────────────────┐
                          │ S7 C2 回归同步      │
                          │ 载荷同步 + 全量回归 │
                          └───────────────────┘
```

**并行化说明**：
- 并行组 1：**S1**（零依赖；纯函数内核，其余全部依赖它）
- 并行组 2：**S2 / S3 / S4 / S5**（均依赖 S1；逻辑可并行，但四者同改 `pick_model.py`
  单文件 ⇒ 实际按序落盘以免编辑冲突）
- 并行组 3：**S6**（依赖 S2–S5，文档需引用已落地的命令契约）
- 并行组 4：**S7**（依赖 S6，最后收口）

## Slice Execution Plan

| # | 优先级 | 风险 | 预估工时 | 并行组 | TC 覆盖 | 实现目标 | 依赖 |
|---|--------|------|---------|--------|---------|---------|------|
| 1 | P0 | 🟢 Low | S | 组1 | TC-UOB-005,006,007,008,010 | `_classify_onboard_models()` / `_config_hash()` / `_onboard_due()` / `migrate_to_relay_onboard()` | 无 |
| 2 | P0 | 🟡 Med | M | 组2 | TC-UOB-001,002 | `cmd_onboard`（读）：system/custom/agenthub + 桥接扫描预填 | 1 |
| 3 | P0 | 🟡 Med | M | 组2 | TC-UOB-003,004,011 | `cmd_onboard_set`（写）：逐自定义/桥接 window 覆写 + free_allowlist + relay_onboard | 1 |
| 4 | P0 | 🟢 Low | S | 组2 | TC-UOB-005,006,007,008 | `cmd_onboard_status` + 子命令注册（消费 S1 的 `_onboard_due`） | 1 |
| 5 | P0 | 🟢 Low | S | 组2 | TC-UOB-009 | `cmd_next` / `cmd_inventory` 透传 `onboard_due` | 1 |
| 6 | P1 | 🟡 Med | M | 组3 | TC-UOB-012 | SKILL.md `relay-onboarding-wizard` 块（4 段）+ 旧 `relay-window-wheel` 保留 fallback + `relay_instruction.md` Step 0 | 2,3,4,5 |
| 7 | P1 | 🟡 Med | M | 组4 | TC-UOB-013 | `test-free-model-confirm.py` 文案断言同步 + `_sync_install_payload.py` + `verify_payload.py` + 全量回归 | 6 |

## Rationale

### Slice 1: 纯函数内核（P0，先行）
- **依赖关系**：S2/S3/S4/S5 全部消费这里的 `_classify_onboard_models`（系统/自定义/桥接分类）、
  `_onboard_due`（due 四态）、`migrate_to_relay_onboard`（存量派生）。先落内核可让四命令并行。
- **风险分析**：🟢 Low。纯函数、零 I/O、零网络；经验库暂无匹配条目（0 条）。
  唯一外部依赖是 `now_utc()`（注入 now 即可确定性测试）。守 TC-TEST-003（单一时间源）。
- **工作量估算**：S —— 4 个小函数，逻辑直给（分类靠 `_source`/owner 标记；hash 靠规范化 JSON；
  due 三条件或；迁移靠防御归一化）。

### Slice 2: onboard（读）命令（P0）
- **依赖关系**：消费 S1 的分类；消费既有 `_per_model_window_view()`、扫描器 `by_id`、`origins` 分类。
- **风险分析**：🟡 Med。桥接扫描（R-BRIDGE）须**零阻断**——端点不可达静默回落 all-day；
  输出须为纯只读（SC-001 断言 SHALL NOT 改 state/models.json）。
- **工作量估算**：M —— 组装 JSON + 桥接探针注入点（`_probe`）。

### Slice 3: onboard set（写）命令（P0）
- **依赖关系**：消费 S1 的分类（决定哪些模型写 window、哪些跳过）。
- **风险分析**：🟡 Med。写路径必须复用 `_write_override_window`（既有非法值不落盘契约）；
  系统模型必须**跳过**写入（R-SYS）；AgentHub 双层（R-AGHUB）不得误写 `agenthub_onboarded`。
- **工作量估算**：M —— 遍历写 + state 一次落盘。

### Slice 4: onboard-status 命令（P0）
- **依赖关系**：消费 S1 的 `_onboard_due`；注册子命令。
- **风险分析**：🟢 Low。薄包装：读 state → 算 due → 出 JSON。
- **工作量估算**：S。

### Slice 5: next / inventory 透传（P0）
- **依赖关系**：消费 S1 的 `_onboard_due`；在既有两命令输出**只增字段**（向后兼容）。
- **风险分析**：🟢 Low。只增 `onboard_due` 布尔，不改既有键语义（既有测试套件守这一点）。
- **工作量估算**：S。

### Slice 6: C1 文档（P1）
- **依赖关系**：依赖 S2–S5 已落地（文档描述真实命令契约，避免"文档先行"漂移）。
- **风险分析**：🟡 Med。R-DEP：旧 wheel 静态断言（test-free-model-confirm.py / probe-wheel-*）
  会因改写假红 ⇒ 必须保留旧块 + S7 同步断言。
- **工作量估算**：M —— 新块 HTML（4 段）+ 旧块保留 + instruction Step 0 改写。

### Slice 7: C2 回归同步（P1）
- **依赖关系**：依赖 S6 文档定稿（载荷快照才稳定）。
- **风险分析**：🟡 Med。载荷一致性（EXP-2026-0009）：改 SKILL.md/pick_model.py 后必须
  `_sync_install_payload.py` + `verify_payload.py`，否则 install.sh 与源漂移。
- **工作量估算**：M —— 跑同步脚本 + 全量回归 + 修文案断言。

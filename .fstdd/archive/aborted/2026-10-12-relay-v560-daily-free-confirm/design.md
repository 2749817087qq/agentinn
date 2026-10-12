# 免费模型确认改为「每天一次」（自然日 + 代码级每日闸）- 技术设计

## Context

**当前系统状态**：`free-model-relay` 的免费模型显式确认（Step 0 第 ② 步）采用「每次触发都弹窗确认」的工作流。
`free_allowlist` 已持久化在 `state` 的独立键 `"free_allowlist" = {"ids": [...], "confirmed_at": "<ISO>"}`
（`pick_model.py` L1790–1819）。`free set` 落盘时写入 `confirmed_at = now_utc().isoformat()`（L2161–2162），
`free clear` 清空为 `None`（L2114）。`next` / `inventory` 已 emit `free_allowlist` 字段，但**没有**「 today 是否还需再确认」的判定。

**约束条件**：
- `now_utc()` 是本脚本**唯一**的时间源（L148–153，返回 `datetime.now()` 本地时间；测试 monkeypatch 它注入假时间）。
  既有 `TC-TEST-003`「全仓 `datetime.now` 调用只许出现 1 次」——**任何新代码都不得再直接调用 `datetime.now()`**。
- `confirmed_at` 实际按**本地**时间落盘（naive ISO），无时区后缀。
- `state` 归一化保留未知键（`normalize_state` / `save_state` 不清未知键，TC-MAINT-004/005 已断言），
  故复用 `confirmed_at` 不新增任何文件或字段存储面。
- 测试对运行机真实 `HOME` / `models.json` 有隔离要求（`_bind_temp` 在临时目录），不能污染真实 state。

**触发诉求**（用户原话）：「取消免费模型的每次使用确认，就每天进行一次确认就行了」。
即把第 ② 步从「每次触发弹窗」降级为「自然日口径、每天首次触发若到期才弹窗」。

## Decisions

### 1. 自然日口径：本地日历日期比较

**方案**：用 `confirmed_at` 的**本地** `.date()` 与 `today = now_utc().date()` 比较；
二者不等（或从未确认）则 `due=True`。

**为什么**：诉求明确是「自然日」而非滚动 24h。用户跨时区/夏令时按运行机本地自然日判定，
语义最直观；且 `confirmed_at` 本就按本地存，无 UTC↔本地转换歧义。

**备选方案及排除原因**：
- 滚动 24h 窗口（上次确认 + 24h）：不符合「每天一次」的朴素认知，且跨午夜会出现「当天不用、次日一早仍有效」的怪异窗口。
- 比较 UTC 日期：会让「本地午夜前后」的确认跨天判定漂移，违背自然日直觉。

### 2. 零新增存储：复用 `free_allowlist.confirmed_at`

**方案**：不新增 state 字段 / 不新增文件。每日闸完全由现有 `confirmed_at` 派生。
`free set`（写当天 confirmed_at）天然「重置当日已确认」；`free clear`（清为 None）天然「使次日重新到期」。

**为什么**：`confirmed_at` 已存在且被策略切换保留逻辑保护（L2228–2235：`FREE_ALLOWLIST_KEY` 在 state 重建时一并保留，
TC-FMC-005 守这一点）。复用即零新增损坏面、零新增锁。

**备选方案及排除原因**：
- 新增 `free_confirmed_date` 独立字段：冗余，且与 `confirmed_at` 易漂移；被否决。

### 3. 新增只读命令 `free confirm-status` 暴露完整判定

**方案**：`free` 子命令新增 `confirm-status` 动作（choices 加 `"confirm-status"`），**只读**不改 state，
输出 `{due, confirmed_at, confirmed_date, today}` + `state`(unset/applied) + `count`。

**为什么**：把「是否到期」的判定收敛到单一权威入口，Agent 层既可 `free confirm-status` 显式查询，
也可读 `next`/`inventory` 透传的 `free_confirm_due` 布尔。判定逻辑集中、可单测。

### 4. `free_confirm_due` 布尔透传进 `next` / `inventory`

**方案**：在 `cmd_next` 与 `cmd_inventory` 的输出 JSON 各加一个布尔字段 `free_confirm_due`，
值 = `_free_confirm_status(meta.get("confirmed_at"))["due"]`。

**为什么**：Agent 层在「每次触发」的冷路径（next）与「勾选前」的 inventory 路径都能直接拿到判定，
据此决定是否弹确认窗——这正是把「每次弹」改为「到期才弹」的执行支点。

**备选方案及排除原因**：
- 在 next/inventory 输出完整 status 嵌套对象：与既有瘦输出风格冲突，且 Agent 只需要一个布尔决策位；完整判定已可由 `free confirm-status` 取得。

### 5. 解析失败防御：脏 `confirmed_at` 按「到期」处理但保留原值

**方案**：`datetime.fromisoformat(confirmed_at)` 抛异常时，判定 `due=True`（当成未确认，重新弹确认），
但 `confirmed_at` 原样回显供排查，不静默吞掉。

**为什么**：脏数据若按「已确认」处理会把每日闸卡死成「永不弹」，比「多弹一次」危险得多。

## Architecture

```
                ┌─────────────────────────────────────────────┐
                │  state["free_allowlist"] =                  │
                │    {"ids":[...], "confirmed_at":"<本地ISO>"} │
                └─────────────────────────────────────────────┘
                                  │ load_free_allowlist(state)
                                  ▼
                ┌─────────────────────────────────────────────┐
                │  _free_confirm_status(confirmed_at, now=None)│
                │    now = now or now_utc()   # 唯一时间源     │
                │    today = now.date().isoformat()            │
                │    due = (confirmed_at 缺/脏) or             │
                │          (confirmed_date != today)           │
                │    → {due, confirmed_at, confirmed_date, today}
                └─────────────────────────────────────────────┘
                       ▲                      │
        free confirm-status (只读)             │ free_confirm_due = due
                       │                      ▼
                  JSON 输出            cmd_next / cmd_inventory
                                      → 输出加 free_confirm_due 布尔

  Agent 层决策：free_confirm_due==True 才弹「确认免费模型」窗；
                ==False 沿用上次确认，直接进选模型。
  free set  → 写 confirmed_at=now_utc()  → 当日 free_confirm_due 立即变 False
  free clear→ 写 confirmed_at=None       → 下次触发 free_confirm_due 变 True（重新弹）
```

**调用链要点**：
- 新增模块级纯函数 `_free_confirm_status(confirmed_at, now=None)`，所有日期访问经 `now_utc()`，绝不新增 `datetime.now()`。
- `cmd_free` 在 `action == "show"` 分支后新增 `action == "confirm-status"` 分支（只读）。
- `cmd_next`：已有 `allowlist_ids, _allowlist_meta = load_free_allowlist(state)`（L2191），
  在其后算 `free_confirm_due` 并并入末尾 `print(json.dumps({...}))`（L2330–2359）。
- `cmd_inventory`：已有 `ids, meta = load_free_allowlist(state)`（L1943），
  在输出 dict（L1962–1973）加 `free_confirm_due`。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 跨时区/夏令时导致「今天」判定与用户预期不符 | 明确按运行机**本地**自然日；符合诉求「自然日」；无 UTC 转换歧义（confirmed_at 本就本地存） |
| 新增 `datetime.now()` 破坏 `TC-TEST-003` | 全部日期访问经 `now_utc()` 单一入口；新代码零 `datetime.now()` 直调 |
| 测试依赖真实时钟导致不确定 | TC 一律注入 `now`（monkeypatch `now_utc` 或 helper 入参 `now=`），不依赖墙上时钟 |
| 既有 `test-free-model-confirm.py` 静态断言「每次触发都弹窗确认」「每次触发都做」会因 C2 文档改写而红 | Phase 3 必须同步更新该断言为「每天首次触发」「free_confirm_due」（C2 文档改写 + 测试维护一并做） |
| 脏 `confirmed_at` 把每日闸卡死成永不弹 | `_free_confirm_status` 解析失败按 `due=True` 处理，原值保留回显 |
| `free set` 之后当天仍弹确认（浪费每日闸） | 验证 `set` 写 today 的 confirmed_at 后 `free_confirm_due` 立即 False（SC-007/TC-DFC-005） |

# free-model-relay v5.6.1：接线 AgentHub 偏好（agenthub_pref 消费端落地） - 技术设计

## Context

- **系统**：`free-model-relay`（免费模型子代理接棒器），核心脚本 `scripts/pick_model.py`（4947 行，纯标准库 CLI）。
- **现状**：v5.6.0 的统一启用向导（`onboard` / `onboard set` / `onboard-status`）第 ④ 段引入 AgentHub 双层：
  `state.relay_onboard.agenthub_pref`（用户意愿）与 `state.agenthub_onboarded`（开通完成态，只由
  `multihub-node-onboarding` skill 写）。**问题**：`agenthub_pref` 写进去后**没有任何消费方** ——
  用户勾选「新对话自动启用 AgentHub 协作中枢」后毫无行为（既不提示、也不发起开通）。
- **约束**：纯标准库、无网络（判据本地派生）；不改 `multihub-node-onboarding` skill；
  `onboard-status` 既有字段向后兼容（只增不改）；state 由 `~/.workbuddy(-ai)` 下的 JSON 文件承载。
- **关键经验（Step 2 交叉检查）**：
  - **EXP-2026-0001（context_loss / high）**：新增 state 键若未纳入「重建 state 的保留集」，策略切换时**静默丢失**。
    ⇒ 直接影响 C3 的落盘位置选择（见 D3）。
  - **EXP-2026-0002（contract_gap / medium）**：复用既有写入函数前须核对其失败语义与粒度。本 change 新增独立
    写入路径（ack），不直接复用 `onboard set` 的整体重建逻辑。

## Decisions

### 1. 派生判据 `agenthub.action` 保持「纯 (pref × onboarded)」，不掺入防打扰状态

**方案**：扩展 `_onboard_agenthub_view(state)`（pick_model.py L4498）返回
`{"pref", "onboarded", "action", "prompted_on"}`，其中
`action = "prompt_enable" if (pref is True and not onboarded) else "none"`。
**为什么**：SC1 明确以 (pref, onboarded) 定义 action，四态可穷举、可客观验证；防打扰是**另一个正交维度**，
单独用 `prompted_on` 表达，避免把两个概念揉进一个字段导致 SC1 不可判。
**备选方案及排除原因**：
- 备选 A：把「今天已提示过」直接并入 `action`（即 action 反映最终是否应发起）⇒ 排除：SC1 的四态断言会被
  `prompted_on` 干扰，且 `action` 语义随时间漂移，不便单测。
- 备选 B：不新增字段，让 Agent 自己组合 pref/onboarded 两布尔 ⇒ 排除：正是当前「无判据 ⇒ 无行为」的根因，
  且不同 Agent 实现易分歧（契约断层）。

### 2. 防打扰用「每自然日一次」而非「一次性」

**方案**：`agenthub.prompted_on` 记录最近一次提示的**本地自然日**；同日不再发起，跨日可再提示一次。
**为什么**：与向导自身 `due` 的「自然日」节奏一致（`_onboard_due` L4438-4439 用 `now_utc().date()`），
心智统一；「一次性」过强（用户当日忽略后永不再提，承诺落空），「每次都提」过吵。
**备选方案及排除原因**：
- 备选 A：一次性（永不重复）⇒ 排除：用户忽略后无补救提示。
- 备选 B：不设限 ⇒ 排除：即用户抱怨的「每次新对话都发起」打扰。

### 3. `agenthub_prompted_on` 落在 `relay_onboard` 内部（而非顶层）

**方案**：存 `state.relay_onboard.agenthub_prompted_on`，与 `agenthub_pref` 同级。
**为什么**：① 语义内聚（AgentHub 子状态）；② **直接规避 EXP-2026-0001** —— 策略切换的保留集
（L2232-2233）已含 `RELAY_ONBOARD_KEY`，整个 `relay_onboard` 天然被保留，无需改保留集；
③ 顶层新键反而要同步改保留集，正是经验库警告的坑。
**备选方案及排除原因**：
- 备选 A：顶层 `state.agenthub_prompted_on` + 改保留集 ⇒ 排除：多一处改动面，且与 `agenthub_onboarded`
  顶层键风格虽一致，但 `agenthub_onboarded` 是**外部 skill** 写的，本键是 relay 自己写，放 relay_onboard 更合适。
- 备选 B：放在 `usage.json` ⇒ 排除：语义不符（非用量数据）。

### 4. 新增写入路径 `onboard agenthub-ack`（扩展 onboard 的 action 枚举）

**方案**：`_dispatch_onboard` 增分支，`onboard` 位置参数 choices 增 `"agenthub-ack"`；
新函数 `cmd_onboard_agenthub_ack` 只改 `relay_onboard.agenthub_prompted_on`（读-改-写，保留其余字段）。
**为什么**：防打扰需要一次「记录已提示」的写操作，而现有 CLI **没有**通用 state 写入口；
挂在 `onboard` 下与 show/set 同族，CLI 心智一致（跟随 free/window 的 action 惯例）。
**备选方案及排除原因**：
- 备选 A：让 `onboard-status`（只读）顺带写 ⇒ 排除：破坏其「只读」契约（SC-001/005~008 均依赖只读）。
- 备选 B：新增顶层子命令 `agenthub-ack` ⇒ 排除：命令面膨胀；且与 onboard 家族割裂。
- 备选 C：复用 `onboard set`（重跑向导）⇒ 排除：语义不符（set 是向导结果落盘，非「已提示」标记），
  且触发 EXP-2026-0002 类「复用副作用函数粒度不符」风险。

### 5. `onboard set` 显式 carry-over `agenthub_prompted_on`

**方案**：`cmd_onboard_set`（L4677）重建 `relay_onboard` 时，读入旧值并带上 `agenthub_prompted_on`。
**为什么**：set 现为**整体重建**该 dict，若不 carry-over，任何一次重跑向导都会清空当日标记 ⇒
用户重跑向导后立刻又被提示一次（体验倒退）。
**备选方案及排除原因**：
- 备选 A：不 carry-over（接受清空）⇒ 排除：制造「刚配完又被问」的打扰。
- 备选 B：把 set 改成 merge 语义 ⇒ 排除：改动面过大，且 set 的「整体落盘」语义是既有设计。

## Architecture

```
Step 0（新对话）：
  relay onboard-status
     └─ _onboard_agenthub_view(state) ── 读 relay_onboard.agenthub_pref
                                       └ 读 state.agenthub_onboarded（外部 skill 写）
                                       └ 读 relay_onboard.agenthub_prompted_on
        ⇒ {pref, onboarded, action, prompted_on}
              │
              ├─ action=="none"                 ⇒ 不动
              └─ action=="prompt_enable" 且 prompted_on != today
                     ⇒ Agent 调 multihub-node-onboarding（本机面板交互）
                     ⇒ 立即 relay onboard agenthub-ack   （记录当日，防重复）
                                └─ 读-改-写 relay_onboard.agenthub_prompted_on = today

落盘位置（state.json）：
  state = {
    "rr_*"/"strategy"/"index"/"history"...,          # 轮次状态（重建时丢弃）
    "free_allowlist": {...},                          # 保留集
    "relay_onboard": {                                # 保留集（整体）
        confirmed_at, groups, custom_periods,
        agenthub_pref,                                # 意愿（向导写）
        last_config_hash,
        agenthub_prompted_on   ← 本 change 新增（ack 写；set carry-over）
    },
    "agenthub_onboarded": true|None                   # 完成态（外部 skill 写）
  }
```

调用链（改动点）：`main()`（action 枚举 + handler）→ `_dispatch_onboard`（+1 分支）→
`cmd_onboard_agenthub_ack`（新）；`_onboard_agenthub_view`（+2 键）；`cmd_onboard_set`（+carry-over）；
`relay_instruction.md` / `SKILL.md`（+联动规则）。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 自动发起开通流程打扰用户 | 每自然日一次（`prompted_on`）；已开通（onboarded）立即静默；文档显式写「偏好≠已开通」 |
| 误把 pref（意愿）当 onboarded（完成态） | `action` 严格 `pref is True and not onboarded`；`onboarded` 只读自 state，relay 绝不写 |
| 新增 state 子键在重建 state 时静默丢失（EXP-2026-0001） | 落在 `relay_onboard` 内，随保留集整体保留；SC-010 专测策略切换存活 |
| `onboard-status` 增字段破坏既有断言 | 只增 `action`/`prompted_on`，`pref`/`onboarded` 语义逐字不变；全量回归 25/25 守门 |
| ack 在 relay_onboard 缺失时写坏状态 | 前置校验：缺失即 `ok=false` 且不落盘（SC-007），退出码 0 |
| 文档规则与代码判据漂移 | 规则文本含可 grep 的关键串（`prompt_enable` / `agenthub-ack`），SC-008/009 断言存在性 |

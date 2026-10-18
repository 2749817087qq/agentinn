# 子代理接棒指令（spawn 时引用本文件）

## 为什么需要本文件

子代理上下文**收不到** `SOUL.md` / `IDENTITY.md` / `USER.md` / `MEMORY.md`
（实测：子代理只有标准系统提示 + team 通信说明，那四份文件在磁盘上存在但要主动 Read 才可见）。
主会话把本文件路径写进 prompt，你读一下就能拿到完整规则。

## 框架限制（先读这段，别白费劲）

实测确认两条硬限制：

1. **作为 teammate 被调起的子代理，工具集里没有 `Agent`。**
   嵌套 spawn 被框架禁掉了。用 ToolSearch 查 `Agent` / `Task` 都是 `Not found`。
   ⇒ 如果你发现自己没有 Agent 工具，**不要伪造**、不要假装派了子代理，
   在自己这一层把任务做完，并在报告里如实说明"第 2 步因无 Agent 工具未执行"。

2. 子代理看得到 `<available_skills>` 列表，但里面每个 skill 只有一句话描述，
   **不包含脚本路径**。所以只听说"用 agentinn"是不够的，必须给本文件路径。

## 接棒流程（四步）

### 0. 确认免费模型（**每次触发都做**，先于选模型）

v5.6.0 起 Step 0 是**统一启用向导**（时段 / 模型 / 归属 / AgentHub 在一处选定）。先判是否到期：

```bash
agentinn onboard-status
```

输出 `{due, confirmed_at, last_config_hash, current_config_hash, today, agenthub}`：

- **`due: false`**（当天已确认且配置未漂移）⇒ **跳过向导**，直接进第 1 步。
- **`due: true`**（未确认 / 跨自然日 / 数据漂移）⇒ 取预填数据并渲染向导：

```bash
agentinn onboard
```

输出 `{system_models[], custom_models[], agenthub}`：

- `system_models` 时段由**宿主程序规范**定义 ⇒ **只读**（`read_only:true`），**不可编辑**。
- `custom_models`（BYOK + 桥接）⇒ **逐模型可选时段**；桥接项（`bridged:true`，如 OW Bridge /
  qoderclicn 直扫）已尝试扫描其免费时段并预填，扫不到则 all-day（`{start_hour:0,end_hour:0}`）。
  Qoder 侧由 agentinn **直接调用官方 `qoderclicn --list-models`** 发现模型（owner=`qoderCliOwner`，
  url **翻转为本地 relay** `http://127.0.0.1:8799/v1`，`qodercli_gateway` 保留真实官方网关
  `https://gateway.qoder.com.cn/v1` 备查，apiKey 留空、由 relay 复用的浏览器会话鉴权），
  **不再依赖已删除的本地网关 `http://127.0.0.1:8210/v1`**。`qoder-free status` 现显示
  `cli_bin` / `cli_found` / `reachable` / `models` / `relay`（子命令名沿用历史，内部走 CLI 直扫 +
  本地 relay）；**使用前必须先 `qoder-free relay-start` 把 8799 端口的 relay 起起来**，否则这 15 条
  模型指向的端点无服务。详见 `SKILL.md`「Qoderclicn 本地 relay」。

用户调整 + 确认后落盘：

```bash
agentinn onboard set \
  --json '{"groups":{"always_free":["hy3"],"platform_window":["hy4-preview"],"custom":["a"]},
           "custom_periods":{"a":{"start_hour":1,"end_hour":5}},
           "agenthub_pref":false}'
```

要点：

- **系统模型**：`onboard set` **不会**为其写时段覆写（宿主规范为准），并在 `skipped_system_models` 里回报。
- **all-day 语义**：`{start_hour:0,end_hour:0}` 表示恒真（全天可用）。
- **AgentHub 双层**：`agenthub_pref`（偏好）与 `agenthub_onboarded`（开通完成态）**分开存储** ——
  偏好为真**不代表**已开通；开通走 `multihub-node-onboarding` skill（本机面板交互）。
- **AgentHub 接线（v5.6.1）**：`onboard-status` / `onboard` 的 `agenthub` 对象含派生判据 `action`
  （`pref is True and not onboarded` ⇒ `prompt_enable`，否则 `none`）与 `prompted_on`（最近一次提示的本地自然日）。
  **联动规则（Step 0 必做）**：
  1. `agenthub.action == "prompt_enable"` 且 `agenthub.prompted_on != 今天` ⇒ **发起** AgentHub 开通流程
     （调 `multihub-node-onboarding` skill，本机面板交互授权）；
  2. 发起后**立即**执行 `onboard agenthub-ack` 记录当日 —— 防打扰，**每自然日一次**：
     ```bash
     agentinn onboard agenthub-ack
     ```
  3. `agenthub.onboarded == true` 或 `agenthub.prompted_on == 今天` ⇒ **跳过**，不再发起/提示。
- 你（子代理）**通常没有提问能力**：如果你是主会话，渲染向导组件；如果你是被调起的子代理，
  把 `onboard` 输出原样回报给主会话，**不要自己猜时段**。
- 白名单为空 → 降级不阻断：`next` 输出 `allowlist: "unset"`，退回既有规则，退出码 0。

> **旧路径（fallback）**：`inventory` + `free set --ids a,b,c` 仍可用（白名单单独落盘）；
> 新向导渲染失败时可回退到 `SKILL.md`「时段滚轮确认窗口」块。

### 1. 选模型

```bash
agentinn next --strategy auto --job <类型>
```

输出 JSON，取 `model` 字段即模型 ID。

**模型 ID 前缀（`model` vs `model_full`，v5.7.4 起）**：`model` 是**裸 ID**（内部恒为裸 canonical，已自动剥离 `custom-local:` 前缀，杜绝双重前缀）；`recommended_prefix` 是脚本按 `_source` 派生出的前缀（`custom-local:` 或空）；`model_full` = `recommended_prefix` + `model`，即**已拼好前缀的成品 ID**。**二选一、禁止叠加**：要么直接把 `model_full` 当作模型 ID 传；要么自己用 `custom-local:` + `model` 拼（平台模型 `recommended_prefix` 为空，拼出来仍是裸 ID）。**绝不要** `custom-local:` + `model_full`，否则变双重前缀、路由失败。自定义/BYOK 模型（`_source=custom`）必须带 `custom-local:` 前缀，漏拼会被平台**静默路由到收费款**——优先用 `model_full` 省心。

**排障（版本 ≥ v5，字段语义已修正）**：
- 命令 **exit 2** 且输出 `error: all models unavailable` → 所有模型都超限/限流。
  看 `blocked` 数组里每个模型的 `reason`，用 `clear-exhausted` 恢复或等限流到期。
- `capability_violation: true` → 该模型不满足任务必需能力（如需要 tool_call 但没有），谨慎使用
- `blocked` 非空 → 有模型被跳过，里面写了原因（不影响本次选择，仅供排障）。
  `不在免费白名单内（未勾选）` 是白名单过滤的产物，**不是错误**。
- `allowlist: "unset"` → 还没确认过免费模型，本次退回既有规则（此时应回到第 0 步）
- `free_quota_exhausted: true` → 勾选的免费模型**全部用完**（无模型可选），需重新勾选或等恢复
- 输出里**没有** `available` 字段：能正常返回就代表模型可用（已过滤过），
  不可用只走上面那条 exit 2。旧文档里"检查 `available: false`"的说法是错的，别找这个字段。

### 2. 传给 Agent

推荐直接用 `model_full`（已带前缀的成品 ID）：

```python
Agent(model="<上一步拿到的 model_full>", prompt="...")
```

也可等价地自己拼（平台模型 `recommended_prefix` 为空，拼出来仍是裸 ID）：

```python
Agent(model=(recommended_prefix + model), prompt="...")
```

**禁止叠加**：对 `model_full` 不要再前缀 `custom-local:`，否则变双重前缀、路由失败。若你没有 Agent 工具，见上面「框架限制」第 1 条。

### 3. 记账（子代理结束后）

```bash
agentinn record --model <id> [--tokens <估算token>]
```
token 拿不到就省略，只记请求数也有意义。**不要编造 token 数字**，估算的要说明是估算。

**看 `quota_alerts`（额度告警）**：非空 = 白名单内有模型刚耗尽/被限流，逐条形如
`{"model": "alpha-model", "kind": "quota_exhausted", "detail": "请求数达上限（1/1）", "source": "custom"}`。

- `kind` = `quota_exhausted`（配额用尽）/ `rate_limited`（临时限流）
- `record` 另有 `quota_exhausted: true/false` —— 本次记账的模型是否**刚**打到上限
- **只覆盖白名单内模型**；未勾选的模型达上限不会出现在这里（但会进 `next` 的 `blocked`）
- 呈现规则：`quota_alerts` 非空 → 在回复**顶部**输出醒目通知块（模型 + `kind` + `detail`）；
  `free_quota_exhausted: true` → 升级为**带选项的提问卡**

## job 类型映射

| 任务性质 | --job 值 |
|----------|----------|
| 代码审查 / 找 bug | `code-review` |
| 写规格 / 设计文档 | `spec-writing` |
| 生成测试 | `test-gen` |
| 文档校对 / 总结 | `doc-review` |
| 检索 / 通用 | `general` |

FSTDD：P1 提案审查→`spec-writing`，P2 经验搜索→`general`，
P3 三路评审→`code-review` / `test-gen` / `doc-review`。

## 时段策略（脚本自动处理，了解一下）

时段确认（Step 0 第 ① 步的滚轮组件）与 `window set` 写回见 `SKILL.md`「时段滚轮确认窗口」；本文件只覆盖子代理接棒流程。

- **免费时段 23:00–08:00**：平台模型（hy4-preview / hy3）免积分 → 优先
- **收费时段 08:00–23:00**：切回自定义模型（deepseek-v4-flash / glm-5.2 / sensenova-6.8-flash-lite），不占平台积分
- 同来源内按工作类型得分 + 相对容差**轮换分摊额度**（不是固定用一个模型）

**活动期会结束**（默认 2026-10-10）。过期后平台模型自动退出调度，
`--source auto` 退化为"只用自定义模型"。

**判断当前状态别猜，跑这个命令**：

```bash
agentinn window
```

关键字段：

| 字段 | 含义 |
|------|------|
| `in_free_window` | 现在是否免费时段 |
| `expired` | 活动期是否已结束（`true` = 平台模型已不参与） |
| `warning` | 活动结束的告警（含结束日期与延长方法）；未过期为 `null` |
| `config_source` | 配置来源：`default` / `models.json` / `override`（覆盖文件 `~/.workbuddy/agentinn-window.json` 生效，优先级最高） |
| `auto_source_now` | `--source auto` 本次解析成 `all` 还是 `custom` |
| `next_change` | 下次时段切换时间与剩余分钟 |

**活动期过期后想继续用平台模型**：在 `~/.workbuddy/models.json` 数组末尾加一个配置元素：

```json
{ "freeWindow": { "until": "2026-12-31" } }
```

（只写要覆盖的字段即可；配置元素要放在数组**末尾**，且不能带 `vendor` 字段。）

## 排障

| 现象 | 处理 |
|------|------|
| `error: all models unavailable`（exit 2） | 全部模型配额满或限流中。`quota show` 查配额，`clear-exhausted <model>` 手动恢复 |
| 返回里有 `source_warning` | 收费时段显式用了 `--source platform/all`，**会产生费用**，改用 `--source custom` |
| 返回里有 `capability_violation: true` | 所选模型不满足该 job 的必需能力，优先换 `--job` 或等限流恢复 |
| `window` 显示 `expired: true` | 活动期已结束，平台模型不再参与；按上文加 `freeWindow` 延长 |
| `config_source` 是 `default` 但你配了 | 配置字段写错了，用 `window` 的 `window_config` 核对哪些字段没生效 |
| 不确定"现在能不能干活" | 跑 `doctor`（纯只读，一次报出全部隐患）|
| doctor 报 `quota_exhausted` | 该模型配额已爆、选不中。`doctor --fix-unsafe` 重置（**会重新启用该模型，可能产生费用**）|
| doctor 报 `all_models_unavailable` | 所有模型都被过滤，`next` 必然 exit 2。跑 `doctor --fix-unsafe` |
| doctor 报 `apikey_placeholder` | models.json 里 apiKey 还是 `YOUR_API_KEY_HERE`，换成真实密钥 |
| doctor 报 `orphan_usage` | `doctor --fix` 清理（安全，不影响调度）|
| doctor 报 `activity_expired` | 平台模型活动期已结束，数组末尾加 `{"freeWindow": {"until": "..."}}` 延长 |
| `--strategy auto requires --job`（exit 1） | auto 策略必须配 `--job`。合法值：`code-review` / `spec-writing` / `test-gen` / `doc-review` / `general`；只是想轮询就用 `--strategy round-robin` |
| 返回里 `cost_applicable: false` | 免费时段，成本不参与打分（平台模型此时免费）。收费时段为 `true`，此时看 `cost_multiplier`（0.29 = 2.9 折）与 `cost_bonus`（+7）|
| 返回里 `allowlist: "unset"` | 还没确认免费模型（第 0 步）。本次按既有规则选，建议先补做确认 |
| 返回里 `quota_alerts` 非空 | 白名单内有模型免费额度用尽/被限流（`kind` 区分）。`next` 会自动换模型；若同时 `free_quota_exhausted: true` 说明勾选的模型全用完，需重新勾选或等恢复 |
| 白名单勾了却选不到某个模型 | 该模型是**非 Custom vendor** 条目，不参与候选集（`free set` 的 `warnings` 会明示）。要么用 `list --source custom` 确认口径，要么把它改成 `vendor: "Custom"` |

## 成本感知

收费时段会按模型的 `cost_multiplier`（价格倍数）给分，让**同等能力下更便宜**的模型优先被选中：

| 字段 | 含义 |
|------|------|
| `cost_multiplier` | 价格倍数（平台 hy4-preview = 0.29，即 2.9 折）；`null` 表示无成本概念 |
| `cost_bonus` | 本次实际加的分（0.29 → +7；免费时段恒为 0） |
| `cost_applicable` | `false` = 免费时段成本不参与；`true` = 收费时段成本已计入 |

**成本只影响排序，不影响能力门槛**：

- 能力不同 → 先比能力，成本无法反转（能力弱的便宜也不会被选中）
- 能力相同 → 比成本
- 能力+成本都相同 → 轮换分摊额度

## 如果你确实有 Agent 工具（主会话场景）

往下派子代理时，把这一句原样写进它的 prompt：
```
先读 ~/.workbuddy/skills/agentinn/relay_instruction.md 并按其接棒流程执行
```
否则规则在你这一层就断了。

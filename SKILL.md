---
name: free-model-relay
summary: "免费模型子代理接棒器 — 显式确认免费模型 + 自动检测新模型 + 按工作性质智能分配"
description: |
  读取 ~/.workbuddy/models.json 中的自定义免费模型，在 FSTDD 四阶段流程的子代理委派点
  用这些模型启动 Agent，实现"每个会话通过子代理接棒使用免费 AI"的目标。
  
  核心能力：
  0. 时段确认 — 每次触发先渲染「时段滚轮确认窗口」（当前时段 / 免费判定 / 倒计时 / 改起止小时），
     排在模型白名单勾选**之前**；回传走 `[relay-window]` 前缀，回传不匹配前缀即降级为普通对话
  1. 显式确认 — 每次触发先枚举**全部**可声明模型（含非 Custom vendor 条目 + 平台内置），
     弹窗让用户勾选"哪些是免费模型"，勾选结果存为白名单，relay 只从白名单内挑
  2. 自动检测 — models.json 新增模型时自动发现，根据能力字段推断工作类型
  3. 智能分配 — 按任务性质（code-review/spec-writing/test-gen/doc-review/general）
     自动匹配最优模型，同分模型间轮询
  4. 流量统计 — 每个模型记录请求数/估算 token/最后使用时间，可设配额
  5. 自动切换 — 模型免费量到（超限/限流）时自动跳过，选下一个可用模型
  6. 双轨模型源 — models.json 自定义模型 + WorkBuddy 平台内置模型（hy4-preview/hy3）
  7. 时段感知 — 平台模型免费时段（由程序缓存扫描器动态判定）自动纳入，收费时段自动切回自定义模型
  8. 多策略 — round-robin / fallback / capability-match / auto 四种调度策略
  9. 额度告警 — 白名单内模型免费额度用尽时弹窗通知（record/next 输出 quota_alerts）
  
  与 FSTDD 的 P1 提案审查、P2 经验交叉检查、P3 C1 三路并行评审三个委派点深度集成。
  
  触发词：免费模型、free model relay、子代理接棒、模型接棒、免费AI、custom model agent、
          free model subagent、模型轮换、relay agent、自动检测模型、智能分配模型、
          流量统计、模型配额、自动切换、免费量到了、hy3、hy4、平台模型、免费时段、
          确认免费模型、免费模型白名单、额度用完、额度告警、
          时段滚轮、免费时段确认、改免费时段、window set、relay-window
version: "5.6.1"
author: agent_created
license: unknown

---

# Free Model Relay v4 — 免费模型子代理接棒器

## 核心理念

WorkBuddy 的 Agent 工具 `model` 参数接受模型 ID。`models.json` 中的自定义模型
（vendor: "Custom"）可以直接作为子代理的运行模型。本 skill 让 FSTDD 流程中的
子代理委派点自动选用这些免费模型，实现成本节约。

**v4 新增**：双轨模型源（models.json 自定义 + 平台内置 hy3/hy4-preview）、免费时段自动切换、流量统计与配额、自动跳过超限模型。

**v5.1 新增**：免费模型**显式确认**（`inventory` 枚举全部可声明模型 → 弹窗勾选 → `free set` 存白名单，relay 只从白名单内挑）、额度耗尽**弹窗告警**（`record`/`next` 输出 `quota_alerts`）。见下文「免费模型显式确认」。

**v5.2 新增**：Step 0 的**时段滚轮确认窗口**（内联 HTML 滚轮：展示当前时段 / 免费判定 / 倒计时，并可改起止小时）、`window set` 写回命令（默认写 relay 侧**覆盖文件** `~/.workbuddy/free-model-relay-window.json`，只有 `--write-models-json` 才动含 API Key 的 `models.json`）、免费时段**三级配置**（覆盖文件 > `models.json` 的 `freeWindow` > 源码默认，逐字段生效）。

**v5.3 新增**：
- **密钥录入 `models add` / `models list`** —— 不再需要手改 `models.json`。支持交互式 `getpass`、非交互 `--from-env <VAR>`（落盘 `${VAR}` 字面量，读时才展开）与 `--stdin`；写盘走「备份 → 原子替换 → 写后重读比对」，任何输出通道都不回显密钥原文。见下文「密钥录入」。
- **免费时段**按模型覆写**（`{default, models}` 新结构 + `window set --model <id>`）与**逐模型 opt-in**：只有**显式声明覆写**的模型才受时段约束；未声明覆写的**自定义模型完全不受时段约束**（由额度决定）。见下文「免费时段（平台模型专有）」。
- **doctor 三档化**：默认**结构档**（零网络，校验 url 必填/形态与 vendor 取值）+ `--check-endpoint` 可达性档 + `--check-key` 有效性档（蕴含前者，每模型至多 1 次探测、`max_tokens=1`、首个失败即停）。见下文「健康检查（doctor）」。

**v5.4 新增**：
- **doctor 工具调用能力探测档 `--check-tools`** —— 不只看模型**声明**支持工具调用，而是发一次**最小工具调用请求**，验证它**真返回** `tool_call`。结论由两个**独立** category 表达：`tool_call_unsupported`（确证不支持）与 `tool_call_unknown`（无法判定）；二者不互相兜底，也不复用 `key_undetermined` / `endpoint_unreachable` / `key_invalid`。探测结论**不写回** models.json（不构成永久能力认定）。蕴含 `--check-key` / `--check-endpoint`，三档共用同一次计费请求（`max_tokens=1`、首个失败即停）。见下文「健康检查（doctor）」。
- **条目所有权** —— `models add` 写入的条目带 `relayOwner` 标记；目标条目带**非 relay 的** `*Owner` 键（如 OW Bridge 写的 `buddyBridgeOwner`）时**默认拒绝**（错误 JSON 带 `code="ownership_rejected"`），`--force` 是唯一放行口、且只解除拒绝不越权；`models list` 每条带 `source` 三态（`relay` / `external` / `unowned`）。见下文「密钥录入」。

**v5.5 新增**：**程序侧免费模型自动发现** —— 扫描宿主程序缓存（两根 `~/.workbuddy/cache/acc-product-config-v3.json`）得到当前免费/折扣模型清单（零 API Key），`is_free_window` / `resolve_source` 优先消费它。

**v5.6 新增**：
- **统一启用向导（Step 0 单次渲染）** —— 时段 / 模型 / 归属 / AgentHub 合并到一个控件（4 段）；新增 `onboard`（读）/ `onboard set`（写）/ `onboard-status`（due 判定 = 未确认 / 跨自然日 / 数据漂移），`next` / `inventory` 透传 `onboard_due`。**系统模型时段用宿主规范（只读）；自定义 / 桥接模型逐模型可选时段**。见下文「统一启用向导」。
- **Qoder-free 本地网关源** —— 自动发现本地 OpenAI 兼容网关（Qoder-free）并纳入默认免费候选池，`qoder-free sync` 强制刷新 / `qoder-free status` 查可达性与已发现模型。见下文「Qoder-free 本地网关源」。

## 统一启用向导（Step 0，v5.6.0 —— 单次渲染）

**为什么**：Step 0 原拆成「时段滚轮 + 模型白名单」两块独立渲染，用户要在多个控件之间来回跳。
v5.6.0 合并为**单次**向导（4 段）：**时段 / 模型 / 归属 / 免费窗口在一处选定**。

### 触发与数据流

```bash
# ① 判是否到期（未确认 / 跨自然日 / 数据漂移）
$PY $SCRIPT onboard-status   # → {due, confirmed_at, last_config_hash, current_config_hash, today, agenthub}
# ② due=true 才渲染向导；先取预填数据
$PY $SCRIPT onboard          # → {system_models[], custom_models[], agenthub, scanner_available}
# ③ 用户调整 + 确认后落盘
$PY $SCRIPT onboard set --json '{"groups":{...},"custom_periods":{...},"agenthub_pref":false}'
```

- **`due: false`**（当天已确认且配置未漂移）⇒ **不渲染向导**，直接继续。
- **系统模型**（`system_models`）时段由宿主程序规范定义 ⇒ **只读**（`read_only:true`），用户不可编辑，
  `onboard set` 也**不会**为其写覆写（`skipped_system_models` 回报）。
- **自定义渠道模型**（`custom_models`，含 BYOK 与桥接）⇒ **逐模型可选时段**；桥接模型
  （`bridged:true`，如 qoder-free / OW Bridge / OpenCode）已尝试扫描其免费时段并预填，
  扫不到则回落 all-day（`{start_hour:0,end_hour:0}` 恒真语义）。

### 四段结构

| 段 | 内容 | 可编辑性 |
|----|------|----------|
| ① 始终免费 | 系统模型（扫描器判定全天免费，如 hy3） | 时段**只读** |
| ② 平台时段 | 系统模型（宿主规范时段，如 hy4-preview） | 时段**只读** |
| ③ 自定义渠道 | BYOK + 桥接（qoder-free / OW Bridge / OpenCode 等） | 时段**逐模型可选**（滚轮） |
| ④ AgentHub | 偏好 toggle + 「立即开通」按钮 | 偏好可切；开通走 multihub skill |

### 组件源码（内联 HTML，零外部依赖）

> 占位符来自 `onboard`（读）输出的 JSON。`{{...}}` 为字段路径，原样取值填入；
> `{{ALWAYS_FREE_ROWS}}` / `{{PLATFORM_ROWS}}` / `{{CUSTOM_ROWS}}` 由 Agent 依
> `system_models` / `custom_models` 逐条生成 `<tr>`（系统行带「只读」标记；自定义行带
> `data-model` + 起止小时 `<input type=number>`）。`{{GROUPS_JSON}}` 为 `onboard` 结果的
> 分组 JSON（`{"always_free":[...],"platform_window":[...],"custom":[...]}`）。

> ⚠️ **注入方式**：同旧滚轮块，必须以**非 `innerHTML`** 方式注入（`innerHTML` 插入的 `<script>` 不执行）。

<!-- relay-onboarding-wizard:start -->
```html
<h2 class="sr-only">统一启用向导</h2>
<div class="ob-root" style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-lg);padding:1rem 1.25rem;font-family:var(--font-sans);color:var(--color-text-primary);">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;">
    <div style="font-size:15px;font-weight:500;">统一启用向导</div>
    <div style="font-size:12px;padding:2px 8px;border-radius:var(--border-radius-md);background:var(--color-background-info);color:var(--color-text-info);">{{DUE_BADGE}}</div>
  </div>

  <section style="margin-bottom:14px;">
    <div style="font-size:13px;font-weight:500;margin-bottom:6px;">① 始终免费 <span style="font-size:11px;color:var(--color-text-tertiary);">宿主规范 · 只读</span></div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{{ALWAYS_FREE_ROWS}}</tbody></table>
  </section>

  <section style="margin-bottom:14px;">
    <div style="font-size:13px;font-weight:500;margin-bottom:6px;">② 平台时段 <span style="font-size:11px;color:var(--color-text-tertiary);">宿主规范 · 只读</span></div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{{PLATFORM_ROWS}}</tbody></table>
  </section>

  <section style="margin-bottom:14px;">
    <div style="font-size:13px;font-weight:500;margin-bottom:6px;">③ 自定义渠道 <span style="font-size:11px;color:var(--color-text-info);">逐模型可选时段（含桥接）</span></div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{{CUSTOM_ROWS}}</tbody></table>
  </section>

  <section style="margin-bottom:14px;">
    <div style="font-size:13px;font-weight:500;margin-bottom:6px;">④ AgentHub</div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;">
      <input type="checkbox" id="ob-aghub" {{AGENTHUB_CHECKED}}> 新对话自动启用 AgentHub 协作中枢
    </label>
    <button id="ob-aghub-enable" style="margin-top:6px;">立即开通 ↗</button>
  </section>

  <div style="display:flex;gap:8px;">
    <button id="ob-apply">确认启用 ↗</button>
    <button id="ob-refresh">刷新状态 ↗</button>
  </div>
</div>
<style>
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.ob-root .ob-ro{font-size:11px;color:var(--color-text-tertiary);}
.ob-root td{padding:4px 6px;border-bottom:0.5px solid var(--color-border-tertiary);}
.ob-root .ob-num{box-sizing:border-box;width:56px;height:28px;text-align:center;font-family:var(--font-mono);background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-sm);color:var(--color-text-primary);}
</style>
<script>
(function(){
  function collectPeriods(){
    var out = {};
    var rows = document.querySelectorAll('.ob-custom-row');
    for (var i = 0; i < rows.length; i++){
      var mid = rows[i].getAttribute('data-model');
      var s = rows[i].querySelector('.ob-start').value;
      var e = rows[i].querySelector('.ob-end').value;
      out[mid] = { start_hour: parseInt(s, 10), end_hour: parseInt(e, 10) };
    }
    return out;
  }
  var apply = document.getElementById('ob-apply');
  if (apply) apply.addEventListener('click', function(){
    var payload = {
      groups: {{GROUPS_JSON}},
      custom_periods: collectPeriods(),
      agenthub_pref: document.getElementById('ob-aghub').checked
    };
    sendPrompt('[relay-onboard] set ' + JSON.stringify(payload));
  });
  var refresh = document.getElementById('ob-refresh');
  if (refresh) refresh.addEventListener('click', function(){ sendPrompt('[relay-onboard] show'); });
  var enable = document.getElementById('ob-aghub-enable');
  if (enable) enable.addEventListener('click', function(){ sendPrompt('[relay-onboard] agenthub-enable'); });
})();
</script>
```
<!-- relay-onboarding-wizard:end -->

> **重渲染前必须先移除**上一轮渲染出的组件片段（`relay-onboarding-wizard` 的 `start` / `end`
> 之间的全部内容），否则会出现两组同 `id` 的控件。

### 回传解析（`[relay-onboard]`）

组件通过 `sendPrompt()` 回传**固定前缀** `[relay-onboard]` 的文本：

| 回传 | 含义 | Agent 动作 |
|------|------|-----------|
| `[relay-onboard] show` | 重新读取 | 重新执行 `onboard` 并重渲染组件；**不写任何文件** |
| `[relay-onboard] set {json}` | 落盘向导结果 | 执行 `onboard set --json '<json>'`；回显 `written_windows` / `skipped_system_models` |
| `[relay-onboard] agenthub-enable` | 立即开通 AgentHub | 调 `multihub-node-onboarding` skill（本机面板交互） |

映射要点：

1. `set` 的 JSON 直接作为 `--json` 入参，**不改造**（`onboard set` 自己校验）。
2. `onboard set` 返回含 `error` ⇒ **原样回显**，不重试、不改其它字段。
3. **不修改系统模型时段** —— 系统模型由宿主规范定义，只读。

### AgentHub 接线（v5.6.1）

`onboard-status` / `onboard` 的 `agenthub` 对象含**派生判据**，Step 0 据此联动：

| 字段 | 含义 |
|------|------|
| `pref` | 偏好（向导 toggle 写入 `relay_onboard.agenthub_pref`） |
| `onboarded` | 开通完成态（**只由** `multihub-node-onboarding` 写） |
| `action` | 派生：`pref is True and not onboarded` ⇒ `prompt_enable`，否则 `none` |
| `prompted_on` | 最近一次「已提示」的本地自然日（`onboard agenthub-ack` 写） |

**联动规则**：

1. `agenthub.action == "prompt_enable"` 且 `agenthub.prompted_on != 今天` ⇒ **发起** AgentHub 开通流程
   （调 `multihub-node-onboarding` skill，本机面板交互授权）。
2. 发起后**立即**执行 `pick_model.py onboard agenthub-ack` 记录当日 —— 防打扰，**每自然日一次**。
3. `agenthub.onboarded == true` 或 `agenthub.prompted_on == 今天` ⇒ **跳过**，不再发起/提示。

### 降级规则

1. 用户消息**不以 `[relay-onboard] ` 开头** ⇒ 当**普通对话**处理，**不执行任何写操作**（降级 ≠ 拒绝服务）。
2. 前缀匹配但 action 不在上表 ⇒ **不猜、不写盘**，回一句"无法识别的启用指令"并重渲染组件。
3. `onboard` 输出**缺少占位符对应字段** ⇒ 退回**纯文本**展示其 JSON，**不要**用猜测值渲染。
4. **新向导渲染失败** ⇒ 回退旧「时段滚轮」块（`relay-window-wheel`，见下节）并打 stderr warning
   （双轨过渡，保留 1 release）。

## 时段滚轮确认窗口（Step 0 第 ① 步 —— 在勾选模型之前）

> ⚠️ **v5.6.0 起本块降级为 fallback**：主路径是上节「统一启用向导」。仅当新向导渲染失败时回退到此块。

**为什么排在最前**：用户要在**勾选模型之前**就知道"此刻是不是免费时段" ——
否则勾完才发现是收费时段，白勾。

### 数据来源

```bash
$PY $SCRIPT window
```

输出 JSON 含 `in_free_window` / `window_config` / `config_source` / `expired` / `warning` /
`next_change{at, change_to, remaining_minutes, note}` / `platform_models` —— 滚轮需要的全在里面。

### 组件源码（内联 HTML，零外部依赖）

把下面的片段作为**内联 HTML** 渲染。`{{...}}` 是占位符，分两类：
- **字段占位符**：占位符名**即** `window` 输出的 JSON 字段路径（如 `{{window_config.start_hour}}`），原样取值填入。
  **唯一例外是布尔/空值**：`{{in_free_window}}` 与 `{{next_change.remaining_minutes}}`
  须按下方「择时提示」表**先转成人类可读文案**再填，**不得直出 `true`/`false`/`null`**。
- **文案占位符**：`{{TIMING_HINT}}` —— **不是字段路径**，由 Agent 按下方「择时提示」表生成整句文案填入。

> ⚠️ **平台原语限制**：WorkBuddy 的"弹窗"原语是**提问卡（选项 ≥2）**，
> 没有连续取值控件，**做不出滚轮**。故时段确认走**内联 HTML 组件**
> （有 `sendPrompt()` 回传通道，可闭环）。

> ⚠️ **注入方式**：该片段必须以**非 `innerHTML`** 方式注入 —— 经 `innerHTML` 插入的 `<script>` **不会执行**，
> 届时两个滚轮会渲染成空白框、按钮无监听。

<!-- relay-window-wheel:start -->
```html
<h2 class="sr-only">平台模型免费时段确认</h2>
<div style="background: var(--color-background-primary); border: 0.5px solid var(--color-border-tertiary); border-radius: var(--border-radius-lg); padding: 1rem 1.25rem; font-family: var(--font-sans); color: var(--color-text-primary);">
  <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px;">
    <div style="font-size: 15px; font-weight: 500;">免费时段确认</div>
    <div style="font-size: 12px; padding: 2px 8px; border-radius: var(--border-radius-md); background: var(--color-background-info); color: var(--color-text-info);">{{in_free_window}}</div>
  </div>
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px;">
    <div style="background: var(--color-background-secondary); border-radius: var(--border-radius-md); padding: 12px;">
      <div style="font-size: 13px; color: var(--color-text-secondary);">当前生效时段</div>
      <div style="font-size: 24px; font-weight: 500;">{{window_config.start_hour}} – {{window_config.end_hour}}</div>
    </div>
    <div style="background: var(--color-background-secondary); border-radius: var(--border-radius-md); padding: 12px;">
      <div style="font-size: 13px; color: var(--color-text-secondary);">配置来源</div>
      <div style="font-size: 24px; font-weight: 500;">{{config_source}}</div>
    </div>
    <div style="background: var(--color-background-secondary); border-radius: var(--border-radius-md); padding: 12px;">
      <div style="font-size: 13px; color: var(--color-text-secondary);">距下次切换（分钟）</div>
      <div style="font-size: 24px; font-weight: 500;">{{next_change.remaining_minutes}}</div>
    </div>
  </div>
  <div style="display: flex; gap: 16px; align-items: flex-end; margin-bottom: 12px;">
    <div>
      <div style="font-size: 13px; color: var(--color-text-secondary); margin-bottom: 4px;">开始小时</div>
      <div class="rw-wheel" id="rw-start"></div>
    </div>
    <div>
      <div style="font-size: 13px; color: var(--color-text-secondary); margin-bottom: 4px;">结束小时</div>
      <div class="rw-wheel" id="rw-end"></div>
    </div>
    <div style="display: flex; gap: 8px;">
      <button id="rw-apply">应用时段 ↗</button>
      <button id="rw-refresh">刷新状态 ↗</button>
    </div>
  </div>
  <div style="font-size: 13px; color: var(--color-text-tertiary);">{{TIMING_HINT}}</div>
</div>
<style>
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.rw-wheel{box-sizing:border-box;height:108px;width:76px;overflow-y:scroll;scroll-snap-type:y mandatory;padding:36px 0;border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);background:var(--color-background-secondary);text-align:center;font-family:var(--font-mono);}
.rw-wheel>div{height:36px;line-height:36px;scroll-snap-align:center;font-size:14px;color:var(--color-text-tertiary);}
.rw-wheel>div.on{color:var(--color-text-primary);font-weight:500;}
</style>
<script>
(function(){
  var START = {{window_config.start_hour}};
  var END = {{window_config.end_hour}};
  function build(id, sel){
    var w = document.getElementById(id);
    for (var h = 0; h < 24; h++){
      var it = document.createElement('div');
      it.textContent = (h < 10 ? '0' : '') + h;
      w.appendChild(it);
    }
    w.scrollTop = sel * 36;
    function nearest(){
      var box = w.getBoundingClientRect();
      var mid = box.top + box.height / 2;
      var kids = w.children;
      var best = 0, bestD = Infinity;
      for (var i = 0; i < kids.length; i++){
        var r = kids[i].getBoundingClientRect();
        var d = Math.abs(r.top + r.height / 2 - mid);
        if (d < bestD){ bestD = d; best = i; }
      }
      for (var j = 0; j < kids.length; j++){
        kids[j].className = (j === best) ? 'on' : '';
      }
      return best;
    }
    w.addEventListener('scroll', nearest);
    nearest();
    return nearest;
  }
  var readStart = build('rw-start', START);
  var readEnd = build('rw-end', END);
  document.getElementById('rw-apply').addEventListener('click', function(){
    sendPrompt('[relay-window] set start=' + readStart() + ' end=' + readEnd());
  });
  document.getElementById('rw-refresh').addEventListener('click', function(){
    sendPrompt('[relay-window] show');
  });
})();
</script>
```
<!-- relay-window-wheel:end -->

> **重渲染前必须先移除**上一轮渲染出的组件片段（即上述 `relay-window-wheel` 的
> `start` / `end` 两个注释标记之间的全部内容）。
> 否则会出现两组同 `id`（`rw-start`/`rw-end`/`rw-apply`/`rw-refresh`），`getElementById` 只命中第一组，第二组成为死控件。

### 择时提示（只提示，不等待）

| 情形 | 展示 |
|------|------|
| `in_free_window: true` | "免费中，距收费时段还有 N 分钟" |
| `in_free_window: false` | "收费中，距下一个免费时段还有 N 分钟" + 一句建议（如"可先只勾自定义模型，等免费时段再勾平台模型"） |
| `next_change.remaining_minutes` 为 `null` | "活动已结束，无后续免费时段" |

- 只提示 + 倒计时：**不阻塞等待、不创建定时任务、不改 `--source auto` 的既有判定语义。**
- 时段判断一律以 `window` 输出为准，**不要**在 Agent 侧另算一遍（避免与 `is_free_window` 自相矛盾）。

### 解析规则（`[relay-window]` 回传）

组件通过 `sendPrompt()` 回传**固定前缀** `[relay-window]` 的文本。Agent 按下表处理：

| 回传 | 含义 | Agent 动作 |
|------|------|-----------|
| `[relay-window] show` | 只看状态 | 重新执行 `window` 并重渲染组件；**不写任何文件** |
| `[relay-window] set start=<0-23> end=<0-23>` | 改起止小时 | 执行 `window set --start-hour <start> --end-hour <end>` |
| `[relay-window] set since=<YYYY-MM-DD> until=<YYYY-MM-DD>` | 改活动期（**组件不产生此形式**，仅供手工输入） | 执行 `window set --since <since> --until <until>` |

映射要点：

1. `start` → `--start-hour`，`end` → `--end-hour`，**不可互换**。
2. 只映射**出现过的**键；未出现的键不传（`window set` 只写传入项，不把默认值整份快照进去）。
3. 执行后**回显** `written_to`（写入路径）与 `window_config`（生效值），让用户确认改到哪、改成了什么。
4. **不修改模型白名单** —— 时段与白名单是两件独立的事。

例：回传 `[relay-window] set start=22 end=7` ⇒ 执行 `window set --start-hour 22 --end-hour 7`，
并回显 `written_to`（写入路径）与 `window_config`（生效值）。

### 降级规则

1. 用户消息**不以 `[relay-window] ` 开头** ⇒ 当**普通对话**处理：
   **不执行任何写操作**、不调用 `window set`、不改覆盖文件或 `models.json`；
   仍正常回答该问题（**降级 ≠ 拒绝服务**）。
2. 前缀匹配但 action 不在上表 ⇒ **不猜、不写盘**，回一句"无法识别的时段指令"并重渲染组件。
3. `window` 输出**缺少占位符对应的字段**（无法取值）⇒ 退回**纯文本**展示 `window` 的 JSON，**不要**用猜测值渲染。
4. `window set` 返回**含 `error` 字段**的 JSON（如 `start=25` 越界）⇒ **原样回显该 `error` 文案**，
   不重试、不改其它字段、不写盘。此时输出里**没有** `written_to` / `window_config`，不要编造。
5. **组件未渲染出 24 项，或用户反馈点「应用时段」无回传** ⇒ 直接给出
   `[relay-window] set start=<0-23> end=<0-23>` 指令模板，请用户**原样回复该行**，Agent 按「解析规则」处理。
   **不得**自行猜一个时段写盘。

## 免费模型显式确认（Step 0 第 ②~⑤ 步）

> ⚠️ **v5.6.0 起本块为 fallback**：主路径是上文「统一启用向导」（`onboard-status` 的 **due 判定**驱动，
> 通常**每天一次**而非每次触发）。仅当新向导不可用时，才回退到本节的 `inventory` + `free set` 流程。

**触发词命中后，先做第 ① 步（时段确认），再做本节四步。** 目的：把"哪些模型算免费"从脚本的隐式口径
（`vendor == "Custom"`）变成**用户显式确认过的白名单**。

### 为什么必须显式确认

`load_models()` 只认 `vendor == "Custom"` 的条目，**非 Custom vendor 的条目会被静默丢弃** ——
用户根本不知道它存在，也无从把它算作免费模型。`inventory` 专门枚举**全部**可声明模型
（models.json 全部合法条目 + 平台内置），把选择权交回用户。

### 流程（第 ②~⑤ 步）

```bash
# ② 枚举全部可声明模型（含非 Custom vendor 条目 + 平台内置）
$PY $SCRIPT inventory
```

输出 `models[]`，每项含 `id` / `name` / `vendor` / `declared_in`（`models.json` / `platform`）/
`default_free`（**预勾选提示，不是结论**）/ `currently_selected`（上次的确认结果，可用于预勾选）。

③ **Agent 层弹窗勾选**：用多选提问把 `models[]` 呈现给用户，`default_free: true` 与
`currently_selected: true` 的预勾选，让用户确认哪些是免费模型。

```bash
# ④ 保存勾选结果（白名单）
$PY $SCRIPT free set --ids alpha-model,beta-model
$PY $SCRIPT free show      # 回看当前白名单
$PY $SCRIPT free clear     # 清空（退回未确认状态）

# ⑤ 正常选模型 —— relay 只从白名单内挑
$PY $SCRIPT next --strategy auto --job code-review
```

### 关键约定

| 约定 | 行为 |
|------|------|
| 确认时机 | **每次触发都弹窗确认**（不落"一次性开关"）—— 一个 change 有 3 个委派点就会弹 3 次，这是明确选择的代价 |
| 白名单语义 | **allowlist**：relay 只从勾选集合里挑；集合外的模型即使可用也不会被选中 |
| 勾选范围 | `inventory` 的**全部**条目（含非 Custom vendor）+ 平台内置 |
| 白名单为空 | **降级不阻断**：退回既有规则，`next` 输出 `allowlist: "unset"`，退出码 0 |
| 勾选过窄 | 勾选的模型全不可用时 `next` **exit 2**（`error: all models unavailable` + `blocked`）—— **不会越过白名单**去选别的模型 |
| 非 Custom 条目 | 可以勾，但 relay **不会调度**它（非 Custom vendor 条目不参与候选集）；`free set` 会给出 `warnings` 明示 |
| `reset` | 保留白名单（它属于用户确认结果，不是轮次状态）；要清空用 `free clear` |

`next` 输出新增字段：

| 字段 | 含义 |
|------|------|
| `allowlist` | `applied`（白名单生效）/ `unset`（未确认，退回既有规则）|
| `quota_alerts` | 白名单内已耗尽/限流的模型告警数组（见下）|
| `free_quota_exhausted` | `true` = 勾选的免费模型**全部用完**（无模型可选）|

> `blocked` 里会多出一种原因 `不在免费白名单内（未勾选）` —— 用来解释"候选集为什么变小了"，
> 不是错误。

### 额度耗尽通知（R2）

`record` 与 `next` 的输出都带 `quota_alerts`（**只覆盖白名单内**模型，未勾选的不打扰）：

```json
[{"model": "alpha-model", "kind": "quota_exhausted", "detail": "请求数达上限（1/1）", "source": "custom"}]
```

- `kind` = `quota_exhausted`（配额用尽）/ `rate_limited`（临时限流）
- `record` 另有 `quota_exhausted: true/false` —— 本次记账的模型是否**刚**打到上限

**Agent 层呈现规则**：

1. `quota_alerts` **非空** → 在回复**顶部**输出醒目通知块（模型 id + `kind` + `detail`），
   说明"该模型的免费额度已用完，后续委派会跳过它"。
2. `free_quota_exhausted: true`（勾选的模型**全部**用完）→ 升级为**带选项的提问卡**
   （例：重新勾选白名单 / 等限流恢复 / 换 `--source custom`）。

> ⚠️ **平台原语限制**：WorkBuddy 的"弹窗"原语是**提问卡（选项 ≥2）**，
> **没有**"纯告知、无需选择"的弹窗。故"弹窗通知卡（仅告知）"的最接近实现是：
> **回复顶部醒目通知块为主，仅在全部用完时升级为提问卡**。

## 密钥录入（`models add` / `models list`，v5.3；条目所有权 v5.4）

不再需要手改 `models.json`（它含明文密钥，手改易错且容易写坏结构）。

```bash
# 交互式录入（密钥不回显）
$PY $SCRIPT models add --id my-model --url https://api.example.com/v1

# 非交互：从环境变量引用 —— 磁盘只存 ${VAR} 字面量，读时才展开（密钥不落盘明文）
MY_KEY=sk-xxxx $PY $SCRIPT models add --id my-model --url https://api.example.com/v1 --from-env MY_KEY

# 非交互：从管道读密钥（自动去尾换行）
echo -n "sk-xxxx" | $PY $SCRIPT models add --id my-model --url https://api.example.com/v1 --stdin

# 只读查看：每个条目标注 present / placeholder / missing + 来源三态 source（绝不回显密钥）
$PY $SCRIPT models list

# v5.4：目标条目带第三方所有权标记（如 OW Bridge 的 buddyBridgeOwner）时默认拒绝，
# --force 是唯一放行口 —— 只解除拒绝，不绕过写入安全协议
$PY $SCRIPT models add --id bridged-model --url https://api.example.com/v1 --force
```

**关键约定**：

| 约定 | 说明 |
|------|------|
| 同 `id` 已存在 | **原地更新**该条目的指定字段（不是追加，也不是取并集） |
| `--url` 必填 | 必须是 `http://` 或 `https://` 开头，否则早失败、不落盘 |
| `--api-key` 参数**不存在** | 有意为之：避免密钥出现在命令行历史 / 进程列表里 |
| `${VAR}` 落盘形态 | 磁盘保留字面量，**消费时**才展开；变量未定义则早失败、不落盘 |
| 安全写协议 | 写前备份 `models.json.bak-<UTC>` → 原子替换 → 写后逐字段重读比对 |
| 密钥遮蔽 | 所有输出通道（stdout / stderr / 错误 JSON / traceback）均不回显密钥原文 |
| 所有权标记（v5.4） | relay 写入的条目带 `relayOwner: "free-model-relay"`；目标条目**已有** `relayOwner` 时**保留原值**（不覆盖） |
| 外部所有权保护（v5.4） | 目标条目带**非 relay 的** `*Owner` 键（键名以 `Owner` 结尾，大小写敏感；已知外部工具：`buddyBridgeOwner` = OW Bridge）⇒ **拒绝写入**：错误 JSON 含 `code="ownership_rejected"` / `owner_keys` / `unknown_marker`，退出码 1，并提示加 `--force` |
| `--force` 语义（v5.4） | **只解除所有权拒绝**——不绕过写入安全协议、不绕过参数校验；且对外部标记条目**不会**补打 `relayOwner`（把别人的条目登记成自己的属越权） |
| `models list` 来源三态（v5.4） | 每条带 `source` 字段：`relay`（relay 写入）/ `external`（带外部 `*Owner` 标记，**优先**判定——与 add 侧「外部标记 ⇒ 需 --force」同口径）/ `unowned`（无任何标记） |

## 模型源（双轨制）

### 来源 1: models.json 自定义模型

配置文件：`~/.workbuddy/models.json`，筛选 `vendor === "Custom"`。
这些是通过 OpenAI 兼容端点配置的模型（示例：deepseek-v4-flash、glm-5.2、sensenova-6.8-flash-lite；**以你自己的 `models.json` 为准**），**额度固定，不分时段**。

### 来源 2: WorkBuddy 平台内置模型

由 WorkBuddy 平台直接提供，**不在 models.json 里**，通过 Agent 工具的 `model` 参数直接指定 ID 使用。
已实测可用：`Agent(model="hy3")`、`Agent(model="hy4-preview")` 均能正常启动子代理。

| 模型 ID | 名称 | 推理 | 上下文 | 说明 |
|---------|------|------|--------|------|
| `hy4-preview` | Hy4 preview | ✅ | 1M | 混元思考模型，增强推理，消耗 0.29x |
| `hy3` | Hy3 | — | — | 平台免费模型 |

> 平台模型注册表写在脚本的 `PLATFORM_MODELS` 常量里。新增平台模型时直接往该列表加条目即可。

### 免费时段（平台模型专有）

平台模型在活动期内按程序缓存扫描器返回的时段享免费额度（hy3 全天免费、hy4-preview 等仅夜间免费，具体以扫描器为准）。兜底默认值为：

```python
# v5.5.0：真实免费/折扣清单由程序缓存扫描器 scan_program_config() 提供，
# 不再在此硬编码具体活动期/时段。以下仅为「扫描器与 models.json 均不可用」时的最后兜底。
FREE_WINDOW_DEFAULT = {
    "since": "2026-09-11",   # 活动开始
    "until": None,           # 活动结束由程序缓存扫描器权威提供
    "start_hour": 23,        # 每晚 23:00（最后兜底）
    "end_hour": 8,           # 次日 08:00
}
```

#### 两种免费语义（v5.3 起明确区分）

| 模型 | 免费机制 | 是否受时段约束 |
|------|---------|---------------|
| 平台内置（`hy3` / `hy4-preview`） | 免费时段 | ✅ **受时段约束** —— 由程序缓存扫描器返回的免费时段判定（hy3 全天、hy4-preview 仅夜间） |
| 自定义（`vendor: "Custom"`）**未声明覆写** | 额度 | ❌ **不受时段约束** —— 可用性由额度决定，任何时刻都可被选中 |
| 自定义**显式声明了覆写** | 覆写时段 | ✅ 按其覆写时段判定 |

> `window` 命令的 `per_model[<id>].constraint` 会标出每个模型属于哪一类：
> `time_window`（受时段约束）/ `quota`（由额度决定）。

**为什么自定义模型默认不受时段约束**：v5.2 的免费时段权重表是
`FREE_WINDOW_WEIGHTS = {"platform": 20, "custom": 0}` —— 时段约束**本就只对平台模型有意义**。
若把时段判定普遍套到自定义模型，它们会在 23–08 之外被意外恢复成收费（静默行为回归）。

#### 按模型覆写免费时段（v5.3）

```bash
# 只给 hy4-preview 覆写为 23-7（其余模型仍走 default 的 23-8）
$PY $SCRIPT window set --model hy4-preview --end-hour 7

# 不带 --model ⇒ 写 default 层，且**保持既有文件形态**（旧扁平结构不升级）
$PY $SCRIPT window set --start-hour 22 --end-hour 7
```

**文件形态契约（重要）**：`window set` **不带** `--model` 时，若文件还是旧的扁平结构就
**保持扁平**（不擅自升级）；已是 `{default, models}` 新结构则只更新 `default` 段并
**原样保留** `models` 覆写。**带** `--model` 时才升级为新结构。这样回退到 v5.2 仍能读。

#### 用 freeWindow 配置延长活动期（无需改源码）

**默认活动期结束后平台模型会退出调度**（`window` 命令会返回 `expired: true` 与告警）。
若平台后续延长了活动，在 `~/.workbuddy/models.json` 的**数组末尾**加一个配置元素即可：

```json
[
  { "id": "deepseek-v4-flash", "vendor": "Custom", "apiKey": "sk-...",
    "supportsToolCall": true, "supportsImages": false, "supportsReasoning": false },
  { "id": "glm-5.2", "vendor": "Custom", "apiKey": "sk-...",
    "supportsToolCall": true, "supportsImages": false, "supportsReasoning": false },

  { "freeWindow": { "since": "2026-09-11",
                    "until": "2026-12-31",
                    "start_hour": 23,
                    "end_hour": 8 } }
]
```

只写要覆盖的字段即可，其余沿用默认值（例如只写 `until`）。

**容错行为**：

| 情况 | 行为 |
|------|------|
| 没有 `freeWindow` 元素 | 用默认值，行为与未配置时完全一致（**缺省行为不变**） |
| 某个字段写错（如 `"until": 20261231`） | **该字段单独回退默认值**，其余字段照常生效 |
| 所有字段都写错 | 整体等于默认值，`config_source` 报 `default`（不谎报已生效） |
| `start_hour` / `end_hour` 超出 0–23，或写成 `true`/`false` | 该字段回退默认值（bool 是 int 子类，需显式排除） |
| `freeWindow` 的值不是对象（如 `"2026-12-31"`） | 整体回退默认值 |
| 配了**多个** `freeWindow` 元素 | 只取数组里**第一个**，其余静默忽略（建议只配一个） |
| 配置元素误带 `id` + `vendor: "Custom"` | 仍被排除在模型列表外（显式过滤，不依赖"用户不会这么写"） |
| models.json 语法错误 / 不是 UTF-8 编码 / 文件不存在 | 整体回退默认值，不报错 |
| 顶层是对象而非数组 | 整体回退默认值（不崩溃） |

生效来源可通过 `window` 命令的 `config_source` 字段确认（`default` / `models.json` / `override`）。
`override` = 覆盖文件 `~/.workbuddy/free-model-relay-window.json` 至少一个字段生效（优先级最高）。
**若 `config_source` 是 `models.json`，仍建议核对 `window_config` 的字段值** ——
只写了一个字段时，其余字段显示的是默认值。

> 为什么配置元素"藏在数组里"：`load_models()` 依赖顶层是数组，
> 改成 `{"models": [...], "freeWindow": {...}}` 会破坏所有现有 models.json。
> 配置元素没有 `vendor` 字段，会被自动过滤掉，不影响模型列表。

### 自动源切换（`--source auto`，默认）

| 当前时段 | auto 解析结果 | 行为 |
|----------|---------------|------|
| 免费时段（由扫描器动态判定） | `all` | 平台模型 + 自定义模型都参与选择 |
| 收费时段（由扫描器动态判定） | `custom` | 只用 models.json 自定义模型（平台模型该时段收费，避开） |

强制指定：`--source platform` / `--source custom` / `--source all` 覆盖自动判断。

### 健康检查（doctor）

**答��"现在能不能干活、为什么不能"—— 先跑这条命令。**

```bash
$PY $SCRIPT doctor
```

默认**纯只读**，不修改任何文件。输出（**以下为示例，非实时结果**）：

```json
{
  "healthy": false,
  "summary": {"error": 1, "warn": 2, "info": 1, "total": 4},
  "issues": [
    {
      "severity": "warn",
      "category": "quota_exhausted",
      "message": "模型 <example-model> 配额已爆（请求 12/10、token 48000/40000），该模型当前无法被选中",
      "fixable": true,
      "fix_hint": "运行 doctor --fix-unsafe 重置配额（会让该模型重新参与调度，可能产生费用）"
    }
  ]
}
```

> ⚠️ 上面是**示例输出**：模型名 `<example-model>` 与数字均为占位，**不代表你的实际状态**。
> 实际结果请以你自己跑出的 `doctor` 输出为准（实时状态另见 `usage` / `quota show`）。
> 文档里的示例**永远不会**替你反映真实配额 —— 别把示例当体检报告读。
> 另：示例里 `summary` 的计数为示意值，`issues` 只列了 1 条；真实输出会列出全部 issue。

| 字段 | 说明 |
|------|------|
| `healthy` | `true` = 无 error 级问题 |
| `summary` | `error` / `warn` / `info` / `total` 计数 |
| `issues[].severity` | `error`（影响可用性）/ `warn`（需关注）/ `info`（状态播报）|
| `issues[].category` | 问题分类，见下表 |
| `issues[].fixable` | 是否可由 doctor 修复 |
| `issues[].fix_hint` | 修复指引（含副作用说明）|

**退出码**：有 `error` → 1，否则 0。
`warn` 与 `info` **不影响**退出码（否则 AI 子代理会把警告当失败处理）。

### 检出的问题分类

| category | 级别 | 含义 |
|----------|------|------|
| `models_missing` / `models_empty` | error | models.json 缺失或无可用模型 |
| `url_missing` / `url_invalid` | error | 某 `vendor=Custom` 条目缺 `url`，或 `url` 非 `http(s)://`（v5.3 结构档） |
| `apikey_missing` | error | 某模型没有 apiKey，完全不可用 |
| `apikey_env_undefined` | error | apiKey 引用的 `${VAR}` 环境变量未定义（v5.3） |
| `all_models_unavailable` | error | 全部模型被过滤，`next` 必然 exit 2 |
| `key_invalid` | error | 密钥被端点拒绝（仅 `--check-key`，v5.3） |
| `quota_exhausted` | warn | 某模型配额已爆 → 该模型选不中 |
| `apikey_placeholder` | warn | apiKey 仍是 `YOUR_API_KEY_HERE` 之类占位符 |
| `vendor_not_custom` | warn | 某条目的 `vendor` 既非 `Custom` 也非空 ⇒ **不会被当作自定义模型使用**（v5.3） |
| `orphan_usage` | warn | usage.json 有孤立条目（模型已删）|
| `activity_expired` | warn | 平台模型活动期已结束 |
| `endpoint_unreachable` | warn | 端点不可达（仅 `--check-endpoint` / `--check-key`，v5.3） |
| `key_undetermined` | warn | 密钥有效性**无法判定**（端点不可达，或密钥形态不可用 —— 不会误报为「无效」，v5.3） |
| `tool_call_unsupported` | warn | 模型确证**不返回** `tool_call`（仅 `--check-tools`，v5.4） |
| `tool_call_unknown` | warn | 工具调用能力**无法判定**（端点不可达 / 密钥无效 / 响应截断或不可解析 —— 不误报为「不支持」，v5.4） |
| `rate_limited` | info | 某模型限流中 |
| `window_status` | info | 当前时段 + 活动期配置来源 |

### 联网检查档（v5.3 起分档，v5.4 加工具调用档；默认关闭）

```bash
$PY $SCRIPT doctor --check-endpoint   # 可达性档：对每个 url 做连通性探测（含超时上限）
$PY $SCRIPT doctor --check-key        # 有效性档：发一次最小请求校验密钥（蕴含 --check-endpoint）
$PY $SCRIPT doctor --check-tools      # 工具调用档：发一次最小工具调用请求，验证模型真返回 tool_call（蕴含 --check-key）
```

| 约定 | 说明 |
|------|------|
| 默认零网络 | 不带开关时 `doctor` **不发起任何网络请求**（可安全放进 CI）；修复层（`--fix` / `--fix-unsafe`）不属联网开关，可与之并存 |
| 蕴含关系 | `--check-key` **蕴含** `--check-endpoint`：端点不通就无从判定密钥；`--check-tools` **蕴含**二者（v5.4） |
| 成本约束 | 每模型**至多 1 次**探测请求、单次 `max_tokens = 1`、**首个失败即停**；三档共用同一次计费请求（端点档的免费 `GET` 不计入） |
| 费用提示 | 发请求**前**向用户打印「将要发生的真实 API 调用与费用」提示（走 stderr，不污染 JSON 输出） |
| 安全 | 问题描述**绝不**包含密钥原文 |
| 判定口径 | 只有 401/403 才判「密钥无效」；其它 4xx/5xx 一律「不确定」（不误报） |
| 工具调用判定（v5.4） | `--check-tools` 的结论由**两个独立** category 表达：`tool_call_unsupported`（确证不返回 `tool_call`）/ `tool_call_unknown`（无法判定）；二者**不互相兜底**，也不复用 `key_undetermined` / `endpoint_unreachable` / `key_invalid`；探测结论**不写回** models.json |

### 分层修复（三档，费用安全）

```bash
$PY $SCRIPT doctor              # 纯只读
$PY $SCRIPT doctor --fix        # 只清理真孤立条目（安全）
$PY $SCRIPT doctor --fix-unsafe # ⚠️ 额外清限流 + 重置配额
```

| 档位 | 修什么 | 副作用 |
|------|--------|--------|
| `--fix` | usage.json 里**真孤立**的条目（模型已从 models.json 删除，用量无意义）| 无 —— 该模型本就不会被 `load_models` 加载 |
| `--fix-unsafe` | 额外清 `exhausted_until`、重置超限配额的 requests/tokens | **会让原本不可用的模型立即重新参与调度，下一次调用可能产生真实费用** |

> ⚠️ **平台模型的用量不会被清理。**
> `hy3` / `hy4-preview` 来自源码 `PLATFORM_MODELS`，本就不在 models.json 里，
> 但它们是用量统计的合法记录 —— `--fix-unsafe` 不会清零、不会删除它们。

**修复前自动备份**：每次修复都会先把 usage.json 复制为
`free-model-relay-usage.json.bak-<时间戳>`，输出里的 `backup_path` 字段给出路径与回滚命令：

```bash
cp <backup_path> ~/.workbuddy/free-model-relay-usage.json   # 回滚
```

### 排查决策树

```bash
$PY $SCRIPT doctor
```

| doctor 报什么 | 怎么办 |
|--------------|--------|
| `all_models_unavailable` | `doctor --fix-unsafe`（会重新启用模型，注意费用）|
| `quota_exhausted` | 该模型选不中；要么 `--fix-unsafe` 重置，要么调大 `quota set --max-requests` |
| `apikey_missing` / `apikey_placeholder` | 改 models.json 填真实 key |
| `orphan_usage` | `doctor --fix`（安全）|
| `activity_expired` | 在 models.json 末尾加 `{"freeWindow": {"until": "..."}}` 延长 |
| 一切正常但仍选不到模型 | 跑 `window` 看时段（收费时段 `--source auto` 只用自定义模型）|

## 时段查询

```bash
$PY $SCRIPT window
```

输出字段：

| 字段 | 说明 |
|------|------|
| `now` | 本机当前时间（`expired` / `next_change` 的计算基准） |
| `in_free_window` | 当前是否处于免费时段 |
| `reason` | 判定原因（人可读） |
| `window_config` | 本次生效的完整时段配置 |
| `config_source` | 配置来源：`default`（默认值）/ `models.json`（已配置）/ `override`（覆盖文件生效） |
| `expired` | 活动期是否已结束。`true` 时平台模型不再参与调度 |
| `warning` | 活动期结束的告警文案（含结束日期与延长方法）；未过期时为 `null` |
| `auto_source_now` | `--source auto` 本次解析结果：`all`（免费时段，含平台）/ `custom`（收费时段） |
| `next_change` | 下次时段切换的时间与剩余分钟 |
| `platform_models` | 平台模型 ID 列表 |
| `timezone_note` | 时段按本机本地时间判断 |

### `next` / `list` 的成本字段

| 字段 | 说明 |
|------|------|
| `cost_multiplier` | 价格倍数（平台 hy4-preview = 0.29，即 2.9 折）；`null` 表示无成本概念 |
| `cost_bonus` | 本次实际加的分（0.29 → +7）；免费时段与非法值恒为 0 |
| `cost_applicable` | `false` = 免费时段成本不参与；`true` = 收费时段成本已计入 |

> `cost_applicable` 用来区分「成本不适用」与「成本倍率正好 1.0」——
> 只看 `cost_bonus == 0` 无法分辨这两种情况。

## 自动检测机制

当 `models.json` 新增模型时，`scan` 命令会自动发现并推断其工作类型：

1. **检测差异**：对比 state 文件中 `known_models` 列表与当前 models.json
2. **推断工作类型**：根据新模型的能力字段 + 名称启发式，推断适合的工作类型
3. **立即可用**：新模型无需手动注册，scan 后直接进入 auto 策略的候选池

### 工作类型推断规则

| 工作类型 | 必需能力 | 加分能力 | 说明 |
|----------|----------|----------|------|
| `code-review` | tool_call | reasoning | 代码审查，推理能力加分 |
| `spec-writing` | tool_call | reasoning | 规格编写，推理能力加分 |
| `test-gen` | tool_call | — | 测试生成 |
| `doc-review` | — | tool_call | 文档审查，工具调用加分 |
| `general` | — | — | 通用任务 |

### 名称启发式

模型 ID/名称中包含以下关键词时，对对应工作类型加分：

| 关键词 | 擅长领域 | 说明 |
|--------|----------|------|
| `deepseek` | code-review, spec-writing | DeepSeek 系列擅长代码和逻辑 |
| `glm` | general, spec-writing | GLM 系列通用能力强 |
| `qwen` | code-review, general | Qwen 系列代码能力突出 |
| `flash` | doc-review, general | Flash 系列轻量快速 |
| `lite` | doc-review, general | Lite 系列轻量 |
| `reason` | code-review, spec-writing | 推理模型 |
| `o1` | code-review, spec-writing | 推理模型 |
| `mini` | doc-review, general | Mini 系列轻量 |

## 调度策略

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `round-robin` | 按顺序轮换，每次选下一个 | 均匀分摊负载 |
| `fallback` | 先用首选，失败切备选 | 容错优先 |
| `capability-match` | 按能力字段过滤（tool_call/images/reasoning） | 精确能力匹配 |
| `auto` | **按工作性质智能分配**，同分模型间轮询 | **推荐，FSTDD 默认** |

默认策略：`round-robin`（未传 `--strategy` 时）。**FSTDD 流程务必显式传 `--strategy auto --job <类型>`**，
状态文件 `~/.workbuddy/free-model-relay-state.json` 记录轮次和已知模型。

> `--job` 是 `--strategy auto` 的**必填参数**。缺失时会报错退出（exit 1）并给出
> `valid_types` 列表与替代方案指引 —— 不会静默降级为某个默认工作类型，
> 避免调用方误以为按预期类型做了智能分配。
> 合法值：`code-review` / `spec-writing` / `test-gen` / `doc-review` / `general`。
> 若只是想轮询均匀分摊，用 `--strategy round-robin`（不需要 `--job`）。

### auto 策略的"同档轮换"机制

`auto` 按工作类型打分后，把**同来源、且裸分差在容差内**的模型组成"同档组"，
在组内轮流选，避免把额度全压在单个模型上。

容差 = `max(TIE_TOLERANCE=5, 裸分最高值 × TIE_RATIO=0.6)` —— 绝对下限保证低分场景不过度收敛，
相对比例保证高分场景下容差随分数自适应。

### 成本感知（收费时段）

平台模型的 `cost_multiplier` 表示价格倍数（hy4-preview = 0.29，即 2.9 折）。
收费时段按 `round((1.0 - cost_multiplier) × 10)` 给分，让**同等能力下更便宜的**优先被选中：

| cost_multiplier | 成本加分 | 含义 |
|-----------------|---------|------|
| 0.29 | +7 | 2.9 折 |
| 1.0 | 0 | 原价，无折扣 |
| null / 非法 | 0 | 无成本概念或配置错误，退化为"不考虑成本" |
| （免费时段） | 0 | 平台模型此时免费，成本不参与 |

**关键：成本只影响排序，不影响同档判定。**

打分用两个基准：

- `total` 总分 = 能力分 + 来源权重 + 成本加分 → **用于排序**
- `raw` 裸分 = 能力分 + 来源权重 → **用于算容差与同档分差**

原因：容差是 `max(5, top × 0.6)` 的相对形式。若 top 用 total，
成本加分会同步放大容差 —— 实测 10 分的模型加 7 分后容差从 6.0 涨到 10.2，
把能力差 10 的弱模型错误拉进同档组，削弱能力门槛。

由此推出的语义：

- **能力不同 → 先比能力**（裸分差 > 容差，能力强的稳定胜出，成本无法反转）
- **能力相同 → 比成本**（裸分差 ≤ 容差进入同档，总分高的排前）
- **能力+成本都相同 → 轮换分摊额度**

> v4.0 的纯绝对阈值在真实配置下会导致轮换失效（连续 5 次返回同一模型），
> v4.1 起改为组合容差。

## 来源优先级（按时段动态，成本优先）

来源权重**随免费时段自动反转**，兼顾成本与能力：

| 时段 | 优先来源 | 权重 | 理由 |
|------|----------|------|------|
| **免费时段**（由扫描器动态判定） | `platform`（hy4-preview / hy3） | platform +20 | 平台模型免积分 → 优先用 |
| **收费时段**（由扫描器动态判定） | `custom`（自定义模型） | custom +20 | 平台模型该时段收费，切回外部免费 API（不占平台积分） |

> ⚠️ 权重只影响"来源优先级"，同来源内仍按工作类型得分 + 相对容差轮换。
> 免费时段 `code-review` 下 hy4-preview（10 分）与 hy3（5 分）分差 10 ≤ 容差 18，
> 两者**同档轮换**，不是 hy4 稳定胜出。详见上文「auto 策略的同档轮换机制」。

**想固定成"永远自定义优先"**：把 `source_weights()` 里两个分支都返回 `PAID_WINDOW_WEIGHTS` 即可。

## FSTDD 集成点

本 skill 与 FSTDD 四阶段流程的三个子代理委派点深度集成：

> ### 委派铁律（2026-10-11 踩坑后固化，适用于全部三个委派点）
>
> **① 模型名必须带 `custom-local:` 前缀** —— 启动子代理一律用
> `model = "custom-local:" + next(...)["id"]`（平台内置 hy3/hy4-preview 除外，不带前缀）。
> 裸名若与平台内置模型**同名**（如 `glm-5.2` / `deepseek-v4-flash` / `deepseek-v4-pro` / `kimi-k2.6`），
> 会被平台**静默**路由到平台收费款——无报错、无提示，免费 BYOK 额度完全用不上
> （实测：一次 9 分钟审计窗烧掉 125.3 平台积分，裸名 glm-5.2 的请求全部发往平台计费端点）。
> 另一坑：**不存在的 id 会静默回落**到平台款（同样无报错）⇒ 启动前用 `inventory` / `free list` 核对 id 拼写。
>
> **② 报告「摘要先看、疑点回读」** —— 子代理把**完整结论落成证据文件**
> （如 `deliverables/<topic>-<date>.md`），回传只带「≤15 行摘要 + 文件路径」；
> 主代理**先读摘要**初筛；凡摘要标记 **P0/P1**、或涉及**门禁判据**（Gate 判定、TC 覆盖、
> 失败模式、安全发现）的条目，**必须回读原文件对应章节后再下结论**。
> 不是「只读摘要」——摘要漏报会把藏在细节里的假绿、零覆盖类 P0 静默丢掉；
> 也不是「全文回读」——那会把主会话上下文烧穿。委派省的是子代理推理成本，
> **不省**结论阅读成本，回读按需分配。

### 集成点 1: P1 UNDERSTAND — 提案审查代理

**FSTDD 位置**：`fstdd-understand` Step 3.5（提案自动审查）

**接棒方式**：主代理完成 proposal.yaml 起草后，启动一个子代理执行完整性/清晰度/范围三重审查。
子代理用免费模型运行，审查结论回传给主代理，主代理据此修复或直接进入 Gate 1。

**推荐 job 类型**：`spec-writing`（需要 tool_call + reasoning 加分）

**Agent 调用模板**：
```python
# 先选模型
model = pick_model.next(strategy="auto", job="spec-writing")
# 启动子代理
Agent(
  subagent_type="general-purpose",
  model="custom-local:" + model["id"],   # 委派铁律①：裸名同名会被静默劫持到平台收费款
  prompt="你是 FSTDD Phase 1 的提案审查代理。审查以下 proposal.yaml 的完整性、
         清晰度和范围。逐项检查并给出 PASS/FAIL + 修复建议。
         文件路径：<path>"
)
```

### 集成点 2: P2 SPEC — 经验交叉检查代理

**FSTDD 位置**：`fstdd-spec` Step 2（加载匹配经验 + 交叉检查）

**接棒方式**：主代理提取 proposal 结构化数据后，启动子代理执行经验库语义搜索和
模式匹配。子代理用免费模型运行，返回匹配的失败模式清单，主代理据此在 spec
生成时加入检查清单。

**推荐 job 类型**：`general`（经验搜索不需要特殊能力）

**Agent 调用模板**：
```python
model = pick_model.next(strategy="auto", job="general")
Agent(
  subagent_type="general-purpose",
  model="custom-local:" + model["id"],   # 委派铁律①
  prompt="你是 FSTDD Phase 2 的经验匹配代理。从经验库目录 .fstdd/experiences/
         搜索与以下 Capabilities 相关的失败模式。返回 detection_trigger 和
         fix_template 清单。Capabilities：<list>"
)
```

### 集成点 3: P3 BUILD — C1 多路并行技术评审

**FSTDD 位置**：`fstdd-build` C1（多路并行技术评审，3 个并行代理）

**接棒方式**：这是最成熟的委派点。启动 3 个并行 Agent，分别负责代码、测试、文档
三个维度的评审。3 个代理按工作性质分别选最优模型，实现智能并行接棒。

**推荐 job 类型**：
- 代码评审 → `code-review`
- 测试评审 → `test-gen`
- 文档评审 → `doc-review`

**Agent 调用模板**：
```python
# 并行选 3 个模型（同分模型间轮询，避免全选同一个）
model_code = pick_model.next(strategy="auto", job="code-review")
model_test = pick_model.next(strategy="auto", job="test-gen")
model_doc = pick_model.next(strategy="auto", job="doc-review")

# 并行启动 3 个评审代理（在一条消息中发 3 个 Agent 调用；模型名一律带 custom-local: 前缀，委派铁律①）
Agent(subagent_type="general-purpose", model="custom-local:" + model_code["id"], name="code-reviewer",
      prompt="代码评审：检查变更代码的质量、规范、安全性...")
Agent(subagent_type="general-purpose", model="custom-local:" + model_test["id"], name="test-reviewer",
      prompt="测试评审：检查测试覆盖率、边界条件、断言质量...")
Agent(subagent_type="general-purpose", model="custom-local:" + model_doc["id"], name="doc-reviewer",
      prompt="文档评审：检查 spec 与实现一致性、注释完整性...")
```

## 使用流程

### 在 FSTDD 会话中使用（推荐 auto 策略）

0. **先确认时段**（每次触发都做）：`$PY $SCRIPT window` → 渲染「时段滚轮确认窗口」组件，
   用户确认或改起止小时（`window set`）。详见上文「时段滚轮确认窗口」
1. **再确认免费模型**（每次触发都做）：`$PY $SCRIPT inventory` → Agent 层弹窗勾选 →
   `$PY $SCRIPT free set --ids <勾选的 id>`。详见上文「免费模型显式确认」
2. **会话开始**：运行 `$PY $SCRIPT scan` 检测是否有新模型加入
3. **查看画像**：运行 `$PY $SCRIPT profile` 确认每个模型的工作类型
4. **委派点选模型**：按 job 类型选最优模型
   - P1 提案审查 → `next --strategy auto --job spec-writing`
   - P2 经验搜索 → `next --strategy auto --job general`
   - P3 代码评审 → `next --strategy auto --job code-review`
   - P3 测试评审 → `next --strategy auto --job test-gen`
   - P3 文档评审 → `next --strategy auto --job doc-review`
5. **启动子代理**：用选中的模型 ID 作为 Agent 的 `model` 参数
6. **状态持久化**：轮次状态自动写入 state 文件，跨会话保持

### 命令速查

```bash
# Python 解释器（用 PATH 里的 python3 / python，按本机实际环境二选一）
PY="python3"        # 若本机是 python 命令，改成 PY="python"
SCRIPT="$HOME/.workbuddy/skills/free-model-relay/scripts/pick_model.py"

# 列出所有模型 + 推断工作类型（auto 源按时段切换）
$PY $SCRIPT list
$PY $SCRIPT list --source platform    # 只看平台模型
$PY $SCRIPT list --source custom      # 只看 models.json

# 枚举**全部**可声明模型（含非 Custom vendor 条目 + 平台内置），供弹窗勾选
$PY $SCRIPT inventory

# 免费模型白名单（显式确认哪些模型算免费）
$PY $SCRIPT free set --ids alpha-model,beta-model
$PY $SCRIPT free show
$PY $SCRIPT free clear

# 查看平台模型免费时段状态
$PY $SCRIPT window

# 按模型覆写免费时段（不带 --model ⇒ 写 default 层且保持文件形态）
$PY $SCRIPT window set --model hy4-preview --end-hour 7

# 录入 / 查看模型密钥（v5.3；密钥不回显）
$PY $SCRIPT models add --id my-model --url https://api.example.com/v1
$PY $SCRIPT models list

# 健康检查（默认零网络；联网档需显式开关）
$PY $SCRIPT doctor
$PY $SCRIPT doctor --check-endpoint
$PY $SCRIPT doctor --check-key

# 检测新增/移除的模型（新模型自动推断工作类型）
$PY $SCRIPT scan

# 查看每个模型的工作类型画像
$PY $SCRIPT profile

# 流量统计表（请求数/估算token/配额/剩余/状态）
$PY $SCRIPT usage

# 轮询获取下一个模型
$PY $SCRIPT next

# 按工作性质智能分配（推荐，自动跳过超限/限流模型）
$PY $SCRIPT next --strategy auto --job code-review
$PY $SCRIPT next --strategy auto --job spec-writing
$PY $SCRIPT next --strategy auto --job test-gen
$PY $SCRIPT next --strategy auto --job doc-review
$PY $SCRIPT next --strategy auto --job general

# 指定策略
$PY $SCRIPT next --strategy fallback
$PY $SCRIPT next --strategy capability-match --needs tool_call reasoning

# 记录用量（子代理完成后）
$PY $SCRIPT record --model glm-5.2 --tokens 1500

# 设置配额（免费量上限）
$PY $SCRIPT quota set --model glm-5.2 --max-requests 1000
$PY $SCRIPT quota show

# 限流标记 / 恢复
$PY $SCRIPT mark-exhausted --model deepseek-v4-flash --minutes 60
$PY $SCRIPT clear-exhausted --model deepseek-v4-flash

# 重置状态（保留用量统计）
$PY $SCRIPT reset

# 查看当前状态
$PY $SCRIPT status
```

## 注意事项

1. **新模型自动检测**：models.json 新增模型后，`scan` 命令自动发现并推断工作类型，
   无需手动注册。`list` 和 `next` 命令也会动态读取最新 models.json。
2. **智能分配不排除**：auto 策略下，如果某个模型不适合当前 job 类型（必需能力不满足），
   会被排除；如果所有模型都不适合，降级到全部模型参与轮询。
3. **同分轮询**：auto 策略下，得分相同的模型之间轮询，避免总是选同一个。
4. **模型可用性**：免费模型可能限速或临时不可用。`next`/`auto` 选模型时自动跳过
   「限流中」或「超配额」的模型；**全部不可用时命令退出码 2**，输出
   `error: all models unavailable` + `blocked` 清单（每项含原因），**不会返回不可用模型**。
5. **能力限制**：模型不支持图像/推理时，对应工作类型会标记为不适合。
6. **Agent model 参数**：传入的模型 ID 必须与 `models.json` 中的 `id` 字段完全匹配。
7. **状态文件安全**：state/usage 文件位于 `~/.workbuddy/` 下，不在项目目录中，不会被
   git 跟踪或 FSTDD 流程误删。`reset` 只清 state，用量统计在 usage.json 保留。
8. **白名单只从 state 读**：`free set` 写的是
   `~/.workbuddy/free-model-relay-state.json` 的 `free_allowlist` 键（**不新增文件、
   不写 models.json** —— models.json 只读，里面有明文 API Key）。
9. **额度告警不是恒报**：只有**白名单内**模型真达上限/被限流时 `quota_alerts` 才非空；
   未达上限时恒为 `[]`。白名单为空时**恒为 `[]`**（没勾选就没有"勾选的模型用完了"）。
10. **脚本保持非交互**：`pick_model.py` 零交互（无 `input()`/TTY 判断）—— 被 Agent 以管道
    调用时非 TTY，交互会挂死。故"弹窗勾选"由 **Agent 层的多选提问**呈现，脚本只出 JSON。

## 流量统计与自动切换

### 数据模型

每个模型的用量记录在 `free-model-relay-usage.json`（顶层有 `models` 包装层）：
```
{
  "models": {
    "<model_id>": {
      "requests": 12,          # 累计请求数
      "tokens": 45000,         # 累计估算 token 数
      "quota": {"max_requests": 1000, "max_tokens": null},  # 配额（null = 无限）
      "exhausted_until": null, # 限流到期时间戳（临时屏蔽）
      "last_used": "2026-09-22T..."
    }
  }
}
```

轮次状态文件 `free-model-relay-state.json` 另外存**用户确认结果**（不新增文件）：

```json
{
  "strategy": "auto", "index": 2, "history": [], "known_models": [],
  "free_allowlist": {"ids": ["alpha-model", "beta-model"], "confirmed_at": "2026-10-08T21:00:00"}
}
```

`free_allowlist.ids` 为空（或键缺失）= 未确认 → `next` 退回既有规则并标注 `allowlist: "unset"`。

### 自动切换逻辑

`next` 命令在选模型前先做**白名单过滤**（已确认时）再 `filter_available()`：
0. 白名单非空时，先把候选集收敛到白名单内（白名单外的可用模型记进 `blocked`，原因
   `不在免费白名单内（未勾选）`）；白名单为空则跳过本步并标注 `allowlist: "unset"`
1. 跳过 `exhausted_until` 未过期的模型（限流中）
2. 跳过 `requests >= max_requests` 的模型（请求数达上限）
3. 跳过 `tokens >= max_tokens` 的模型（token 达上限）
4. 全部不可用时命令退出码 2，输出 `error: all models unavailable` + `blocked` 清单，不返回不可用模型

### 命令

```bash
# 流量统计表
$PY $SCRIPT usage

# 记录一次用量（子代理完成后调用，tokens 可选）
$PY $SCRIPT record --model glm-5.2 --tokens 1500

# 设置配额（免费量上限）
$PY $SCRIPT quota set --model glm-5.2 --max-requests 1000 --max-tokens 500000
$PY $SCRIPT quota show

# 限流时标记（子代理返回 429/quota 错误时调用）
$PY $SCRIPT mark-exhausted --model deepseek-v4-flash --minutes 60

# 恢复
$PY $SCRIPT clear-exhausted --model deepseek-v4-flash
```

### FSTDD 使用建议

在子代理结束后，主代理调用 `record` 记录用量；若子代理报告限流错误，
先 `mark-exhausted` 再继续后续委派点（下一个 `next` 会自动避开该模型）。

## 路径速查

以下路径中的 `~` 为当前用户主目录（Windows 上通常映射到 Git Bash / PowerShell 的用户目录）。
实际路径由 `pick_model.py` 内部通过 `os.path.expanduser("~")` 解析，与此处写法一致。

| 文件 | 路径 |
|------|------|
| 模型配置 | `~/.workbuddy/models.json` |
| 免费时段覆盖文件 | `~/.workbuddy/free-model-relay-window.json` |
| 轮次状态 | `~/.workbuddy/free-model-relay-state.json` |
| 用量统计 | `~/.workbuddy/free-model-relay-usage.json` |
| 选模型脚本 | `~/.workbuddy/skills/free-model-relay/scripts/pick_model.py` |

# Relay Step 0 重设计：统一启用向导（始终免费 / 平台时段 / 自定义渠道 + AgentHub 双层）

<!-- source_hash: 42879b75cef7defa -->
<!-- generated_at: 2026-10-12T12:42:22+00:00 -->
<!-- canonical: canonical/proposals/2026-10-12-relay-v560-unified-onboarding.yaml -->

## Why

当前 relay Step 0 拆成两块独立渲染：① 时段滚轮（SKILL.md `relay-window-wheel`）+ ② 模型白名单勾选（`free set` / `inventory`），割裂且 UI 拥挤。v5.5.0 扫描器修复后存在 3 类模型分层（始终免费 x0.00 / 平台时段免费 / 自定义 BYOK 额度制），旧 Step 0 无法体现；且**免费时段是逐模型（per-model）属性**（hy3 全天免费 / glm-5.2 夜间免费 / hy4-preview 仅 23:00-8:00），旧全局单滚轮无法表达。daily-free-confirm change 已到 Gate 2 想把「每次确认」降为「每日一次」，但作为单点改造治标不治本；用户已明确要求把时间 + 模型 + 渠道 + 截至时间 + AgentHub 决策合成一个统一控件，新对话自动弹出。AgentHub（MULTIhub 协作中枢）当前无任何 onboarding 入口，与 relay 流程脱节。


## What Changes

- C1（UI）：SKILL.md 替换 `relay-window-wheel:start` 至 `relay-window-wheel:end` 块为新的 `relay-onboarding-wizard:start` 至 `:end` 块；4 段结构：① 始终免费组（hy3/hy3-b/hy3-c，系统模型，时段=宿主程序规范·只读展示）② 平台时段组（GLM/DeepSeek/Kimi，系统模型，渠道可切，时段=宿主程序规范·只读展示，不提供编辑）③ 自定义渠道组（**BYOK + 桥接**：Qoder-free / OpenCode(OW Bridge, 标记 buddyBridgeOwner) / external 等，源分类复用 `origins` 命令；**每个模型单独选时段**：免费时段 / 全天 + 起止小时滚轮，可展开；**桥接模型也尝试扫描其免费时段并预填**，用户可调）④ AgentHub 双层（偏好 toggle + 立即开通按钮）。**分工原则**：系统模型的时段**直接采用宿主程序规范**（不用选 / 不可改，只展示），**只有自定义模型需要逐个选时间段**。同步 relay_instruction.md「Step 0」章节文案。旧 `relay-window-wheel` 块保留 1 个 release 作为 fallback。

- C2（后端）：pick_model.py 新增 `onboard` 子命令（一次性落盘 `state.relay_onboard`：`{confirmed_at, groups, periods, agenthub_pref}`，groups 分 always_free / platform_sys / platform_cust / custom 四类，**periods 为逐模型 `{<id>:{all_day, start_hour, end_hour}}`**）；新增 `onboard-status` 子命令返回 `{due, confirmed_at, last_config_hash, today, drift_detected}`（due=未确认 或 本地自然日 != 今天 或 数据漂移）；`next` / `inventory` 输出增 `onboard_due` 布尔；`window` / `free set` / `free clear` 维持旧行为但标 deprecated。

- C3（agent / 触发）：relay_instruction.md + SKILL.md 新增「Step 0 触发规则」：agent 在新对话冷启动时调用 `onboard-status`；若 due 则渲染统一向导并把 `[relay-onboard]` 前缀回传闭环；非 due 则跳过沿用上次配置。AgentHub 立即开通按钮调 multihub-node-onboarding skill（已有，不重写内部流程）。


### New Capabilities

- **Relay 启用向导（统一 Step 0）**：单次渲染 4 段控件（新对话自动弹），覆盖 v5.5.0 三类模型分层 + **逐模型免费时段** + AgentHub 双层决策。`onboard` 子命令一次性落盘，`onboard-status` 返回 due 判定与数据漂移检测。吸收 daily-free-confirm 的「每日一次」意图，按「自然日 + 数据漂移」双因子判定 due。

- **AgentHub 启用入口**：统一向导内嵌 AgentHub 双层（偏好 toggle + 立即开通按钮调 multihub-node-onboarding），把 AgentHub onboarding 与 relay 流程缝合。偏好与开通完成态分开存储。


### Modified Capabilities

- **免费时段确认 + 免费模型白名单**：合并为统一向导的 ④ 时段约束段（仅平台组系统通道生效）；`window` / `free set` / `free clear` 命令维持以保证向后兼容与回归套件稳定（标注 deprecated，建议迁移至 `onboard`）。

- **Step 0 触发规则**：从「每次触发弹窗」改为「新对话冷启动 + due 判定」：due=true 才弹统一向导；非 due 静默沿用。完全吸收 2026-10-12-relay-v560-daily-free-confirm 的行为意图。


## Success Criteria

- [ ] {'id': 'SC-1', 'description': '统一向导在临时 HOME 下渲染出 4 段结构（始终免费 / 平台时段 / 自定义渠道 / AgentHub），模型按 v5.5.0 三类正确分组（hy3 进 ①，GLM/DeepSeek/Kimi 进 ②，Qoder-free 进 ③）；② 组每个模型行可展开出该模型自己的免费时段（免费时段 / 全天 + 起止小时）。'}
- [ ] {'id': 'SC-2', 'description': 'onboard 子命令一次落盘 state.relay_onboard={confirmed_at, groups, periods(逐模型 {<id>:{all_day,start_hour,end_hour}}), agenthub_pref}；onboard-status 返回 {due, confirmed_at, last_config_hash, today, drift_detected}，未确认 / 跨天 / 数据漂移任一触发 due=true。'}
- [ ] {'id': 'SC-3', 'description': '新对话冷启动：agent 调 onboard-status，若 due=true 渲染统一向导并把 [relay-onboard] 前缀回传；非 due 静默沿用不弹窗。'}
- [ ] {'id': 'SC-4', 'description': 'AgentHub 双层：偏好 toggle 存 state.relay_onboard.agenthub_pref；立即开通按钮调 multihub-node-onboarding skill（mock 测试验证调用契约，不实跑面板）。'}
- [ ] {'id': 'SC-5', 'description': '存量 state 迁移：test 验证 free_allowlist + window_config 存在时，migrate_to_relay_onboard 派生正确 groups/period，迁移后旧键保留只读。'}
- [ ] {'id': 'SC-6', 'description': 'TC-UOB-001~013 全绿；test-free-model-confirm.py 旧 wheel 静态断言同步更新为「统一向导 / 按 due 判定」后通过；全量回归（tests/run-all.py）除已知 pre-existing 环境问题外全绿。'}

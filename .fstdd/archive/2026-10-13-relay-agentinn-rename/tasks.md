# free-model-relay → agentinn 任务清单

> Change: `2026-10-13-relay-agentinn-rename`

## S1 标识层（agentinn-rename，P0）

- [ ] 1.1 新增 `tools/rename_free_model_relay.py`：单次扫描（正则 alternation）+ 左边界 `(?<![A-Za-z])` 替换引擎；规则表长串在前
- [ ] 1.2 引擎自带幂等自测（对已改名文本再跑一次结果不变）
- [ ] 1.3 对 `SKILL.md` 执行内容改名（含 frontmatter `name: agentinn`）
- [ ] 1.4 对 `relay_instruction.md` 执行内容改名（10 处路径）
- [ ] 1.5 对 `scripts/pick_model.py` 执行内容改名（注释 + 工具名派生 `("relay","agentinn")`）
- [ ] 1.6 新增 `tests/test-relay-agentinn-rename.py`：TC-ARN-001/002/004/008（内容双向断言 + 幂等 + 排除区保留）

## S2 入口层（agentinn-rename，P0）

- [ ] 2.1 新增 `bin/agentinn`（POSIX sh）：定位自身 → 转发 `scripts/pick_model.py`（零交互、纯转发）
- [ ] 2.2 新增 `bin/agentinn.cmd`（Windows）：同上
- [ ] 2.3 追加 TC-ARN-005（转发等价）、TC-ARN-006（零交互）到 `tests/test-relay-agentinn-rename.py`

## S3 数据层（data-file-migration，P0）

- [ ] 3.1 `pick_model.py`：`_STATE_NAME`/`_USAGE_NAME`/`_OVERRIDE_WIN_NAME` → `agentinn-*.json`
- [ ] 3.2 新增 `_migrate_legacy_data_files()`：旧文件存在且新文件缺失 ⇒ 只读复制（原子写）；旧文件保留；幂等；失败静默（不复用 `_cli_fail` 路径）
- [ ] 3.3 在 `compute_data_paths`/数据根解析后调用迁移（惰性、一次性）
- [ ] 3.4 `RELAY_OWNER_VALUE="agentinn"` + 新增 `RELAY_OWNER_VALUES={"agentinn","free-model-relay"}`；判定处改集合 `in`
- [ ] 3.5 `_detect_source_tool` relay 分支报告名统一为 `agentinn`，识别兼容旧值
- [ ] 3.6 新增 `tests/test-relay-agentinn-data-migration.py`：TC-DFM-001~008（新文件名 / 迁移 / 旧缺失 / 并存 / 幂等 / owner 三态）

## S4 分发与目录层（agentinn-rename，P0）

- [ ] 4.1 `install.sh`：`SKILL_DIR` → `$HOME/.workbuddy/skills/agentinn`；内嵌载荷中的路径改名；安装 `agentinn` 入口到 `~/.workbuddy/bin/` + 打印 PATH 指引
- [ ] 4.2 `_sync_install_payload.py` / `verify_payload.py`：`SK` 路径改 `agentinn`
- [ ] 4.3 `agenthub-install.sh` / `build_agenthub.py` / `README.md` / `INTEGRATION.md` / `ROADMAP.md` / `pick.py` 同步改名
- [ ] 4.4 两根 skill 目录改名 `free-model-relay/` → `agentinn/`（AI 根 + WB 根）
- [ ] 4.5 载荷重同步 `_sync_install_payload.py` + `verify_payload.py`（双根字节一致）
- [ ] 4.6 追加 TC-ARN-003（文件名维度）、TC-ARN-007（目录改名）到 `tests/test-relay-agentinn-rename.py`

## 5. 质量验证与交付（P0）

- [ ] 5.1 逐切片验证（TC 覆盖 + 产出物核对 + 测试通过）写入 `.fstdd.yaml`
- [ ] 5.2 C1 多路并行评审（代码/测试/文档 3 代理）+ 逐条处置
- [ ] 5.3 C2 全量质量检查（全量回归 + `ci check-failures`）
- [ ] 5.4 C3 Diff 审查（逐文件）
- [ ] 5.5 C4 失败模式检查（22 类全量）
- [ ] 5.6 C5 经验库记录/更新
- [ ] 5.7 C6 `design-adjustments.md`
- [ ] 5.8 C7 `test-report.md`
- [ ] 5.9 Gate 3 用户确认

<!--
优先级说明：
- P0：阻塞性任务，完成前无法进入下一阶段
- P1：重要任务，应在当前阶段完成
- P2：可延后到后续版本的任务
-->

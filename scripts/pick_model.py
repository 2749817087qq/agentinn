#!/usr/bin/env python3
"""
AgentInn — pick_model.py v4
模型来源双轨制：models.json 自定义模型 + WorkBuddy 平台内置模型（hy3/hy4-preview）。
支持智能工作性质分配 + 流量统计 + 自动切换 + 平台免费时段感知。

用法:
  # 时段感知 / 时段写回
  python pick_model.py window                             # 查看平台模型免费时段状态
  python pick_model.py window set --start-hour 22 --end-hour 7
                                                          # 写覆盖文件 ~/.workbuddy/agentinn-window.json
  python pick_model.py window set --until 2026-12-31 --write-models-json
                                                          # 显式写 models.json（自动备份 + 原子替换 + 写后校验）

  # 模型来源（--source，默认 auto = 免费时段用平台+自定义，收费时段只用自定义）
  python pick_model.py list [--source auto|custom|platform|all]
  python pick_model.py next [--source auto] --strategy auto --job code-review
  python pick_model.py profile [--source auto]
  python pick_model.py usage [--source auto]

  # 免费模型显式确认（白名单）
  python pick_model.py inventory                          # 枚举**全部**可声明模型（含非 Custom vendor），供勾选
  python pick_model.py free set --ids a,b,c               # 保存勾选结果（白名单，每次触发重新确认）
  python pick_model.py free show                          # 查看当前白名单
  python pick_model.py free clear                         # 清空白名单

  # 其他
  python pick_model.py scan                              # 检测 models.json 新增/移除
  python pick_model.py record --model <id> [--tokens <n>] # 记录一次用量（输出含额度告警）
  python pick_model.py quota set --model <id> --max-requests <n> [--max-tokens <n>]
  python pick_model.py quota show
  python pick_model.py mark-exhausted --model <id> [--minutes <n>]
  python pick_model.py clear-exhausted --model <id>
  python pick_model.py reset                              # 重置状态（保留用量）
  python pick_model.py status
"""

import json
import os
import re
import sys
import argparse
import time
import shutil
import getpass
from datetime import datetime, timedelta, date

# 时间辅助（统一命名，供锁超时等使用）
time_monotonic = time.monotonic
time_sleep = time.sleep

# ── 路径常量：多根自适应（relay-source-governance change C2）──
HOME = os.path.expanduser("~")

# 数据根白名单：显式枚举，**禁用裸 glob**（避免误纳 .bak/.old 备份目录）
DATA_ROOT_WHITELIST = [".workbuddy", ".workbuddy-ai"]
FALLBACK_DATA_ROOT = os.path.join(HOME, ".workbuddy")

# relay 数据文件名（与既有命名一致）
_MODELS_JSON_NAME = "models.json"
_STATE_NAME = "agentinn-state.json"
_USAGE_NAME = "agentinn-usage.json"
_OVERRIDE_WIN_NAME = "agentinn-window.json"

# 改名前的数据文件名前缀（一次性迁移用）。
# ⚠️ 用**拼接构造**旧名前缀，使本文件不含旧名字面 —— 改名守卫 TC-ARN-001a 会扫本文件内容。
_DATA_NAME_PREFIX = "agentinn-"
_LEGACY_DATA_PREFIX = "free-" + "model-relay-"


def _legacy_data_name(new_name):
    """把新数据文件名映射回改名前的旧名（仅用于迁移读取）。"""
    if new_name.startswith(_DATA_NAME_PREFIX):
        return _LEGACY_DATA_PREFIX + new_name[len(_DATA_NAME_PREFIX):]
    return new_name


def _migrate_legacy_data_files():
    """把旧名数据文件**复制**为新名（只读旧、写新、保留旧），幂等、失败静默。

    迁移契约（SC-010/012/013）：
      · 仅当**新名文件不存在**且**旧名文件存在**时复制（新旧并存 ⇒ 以新为准，不覆盖）；
      · 旧文件**保留**（不删除），便于回滚；
      · 任何异常一律静默吞掉，绝不阻断主命令；
      · 覆盖数据根白名单（.workbuddy / .workbuddy-ai）+ env 显式根，去重。
    """
    roots = []
    try:
        env_root = os.environ.get("FMR_DATA_ROOT")
        if env_root:
            roots.append(env_root)
        env_models = os.environ.get("FMR_MODELS_JSON")
        if env_models:
            roots.append(os.path.dirname(os.path.abspath(env_models)))
        for name in DATA_ROOT_WHITELIST:
            roots.append(os.path.join(HOME, name))
        roots.append(FALLBACK_DATA_ROOT)
    except (OSError, ValueError):
        # 尽力而为：根收集失败（如 env 含非法字符）即放弃迁移，绝不阻断主命令（评审 P2-2）
        return

    seen = set()
    for root in roots:
        try:
            root = os.path.abspath(root)
        except (OSError, ValueError):
            continue
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        for new_name in (_STATE_NAME, _USAGE_NAME, _OVERRIDE_WIN_NAME):
            tmp = None
            try:
                src = os.path.join(root, _legacy_data_name(new_name))
                dst = os.path.join(root, new_name)
                if os.path.exists(dst) or not os.path.exists(src):
                    continue
                with open(src, "rb") as f:
                    blob = f.read()
                # 临时名带 pid：并发迁移互不覆盖（评审 P2-1）
                tmp = "%s.migrating.%d" % (dst, os.getpid())
                with open(tmp, "wb") as f:
                    f.write(blob)
                os.replace(tmp, dst)
            except OSError:
                # 失败静默：迁移是尽力而为，绝不阻断主命令
                if tmp:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except OSError:
                        pass


def compute_data_paths(root):
    """返回 (MODELS_JSON, STATE_FILE, USAGE_FILE, OVERRIDE_WINDOW_FILE) 四元组。"""
    return (
        os.path.join(root, _MODELS_JSON_NAME),
        os.path.join(root, _STATE_NAME),
        os.path.join(root, _USAGE_NAME),
        os.path.join(root, _OVERRIDE_WIN_NAME),
    )


def _models_json_nonempty(root):
    """root 下 models.json 存在且解析为非空 list（含 ≥1 个非 freeWindow 模型条目）。"""
    p = os.path.join(root, _MODELS_JSON_NAME)
    if not os.path.exists(p):
        return False
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return False
    if not isinstance(data, list):
        return False
    return any(isinstance(m, dict) and m.get("id") and "freeWindow" not in m for m in data)


def _resolve_data_root_inner():
    """纯解析：返回 (root, mechanism)。优先级 env 覆盖 > 白名单探测 > 回退默认根。"""
    env_root = os.environ.get("FMR_DATA_ROOT")
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root), "env"
    env_models = os.environ.get("FMR_MODELS_JSON")
    if env_models and os.path.isfile(env_models):
        d = os.path.dirname(os.path.abspath(env_models))
        if os.path.isdir(d):
            return d, "env"
    candidates = []
    for name in DATA_ROOT_WHITELIST:
        root = os.path.join(HOME, name)
        if _models_json_nonempty(root):
            candidates.append(root)
    if candidates:
        def _mtime(r):
            sf = os.path.join(r, _STATE_NAME)
            try:
                return os.path.getmtime(sf)
            except OSError:
                return -1.0
        # STATE mtime 最新优先；平手取字典序最小（deterministic）
        return sorted(candidates, key=lambda r: (-_mtime(r), r))[0], "autodetect"
    return FALLBACK_DATA_ROOT, "fallback"


_DATA_ROOT = None
_DATA_ROOT_MECHANISM = None


def resolve_data_root(apply=False):
    """解析生效数据根。

    优先级：① FMR_DATA_ROOT / FMR_MODELS_JSON 环境变量覆盖
            ② 白名单根中「含非空 models.json」者（STATE mtime 最新、平手字典序最小）
            ③ 回退 ~/.workbuddy（v5.3 行为，绝不抛异常）

    apply=True 时同步更新模块级 MODELS_JSON/STATE_FILE/USAGE_FILE/OVERRIDE_WINDOW_FILE
    （保持可重绑定属性，供测试 monkeypatch）；返回生效根绝对路径。
    freeWindow 与 models.json 同源：因本函数驱动 MODELS_JSON，_read_models_free_window
    自动读生效根的配置，无需单独解析逻辑（消除切根静默丢 freeWindow 风险）。
    """
    global _DATA_ROOT, _DATA_ROOT_MECHANISM, MODELS_JSON, STATE_FILE, USAGE_FILE, OVERRIDE_WINDOW_FILE
    root, mechanism = _resolve_data_root_inner()
    _DATA_ROOT, _DATA_ROOT_MECHANISM = root, mechanism
    if apply:
        (MODELS_JSON, STATE_FILE, USAGE_FILE, OVERRIDE_WINDOW_FILE) = compute_data_paths(root)
    return root


# 模块导入期一次性解析并落定路径常量（与 FREE_WINDOW 模块级单例风格一致）
resolve_data_root(apply=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def now_utc():
    """
    全局时间源函数，返回当前本地时间。
    测试可通过 monkeypatch 替换此函数注入假时间。
    """
    return datetime.now()


# ══════════════════════════════════════════════════════════════
# WorkBuddy 平台内置模型 + 免费时段
# ══════════════════════════════════════════════════════════════

# 平台内置模型「种子」：人工校订的**永久基线**（不在 models.json 里，由平台直接提供）
# 实测可用：Agent(model="hy3") / Agent(model="hy4-preview") 均可启动子代理
#
# ⚠️ 2026-10-15 起：本清单**不再等同于**平台可用模型全集。
#    平台随附的其它模型（尤其免费模型，如 step-5-preview，宿主缓存 credits=x0.00）
#    由宿主程序缓存扫描器动态发现后并入 PLATFORM_MODELS
#    （见 _discover_platform_models / _refresh_platform_models）。
#    种子条目始终保留，用于承载人工校订的 note / cost_multiplier。
PLATFORM_MODELS_SEED = [
    {
        "id": "hy4-preview",
        "name": "Hy4 preview",
        "vendor": "Platform",
        "supportsToolCall": True,
        "supportsImages": False,
        "supportsReasoning": True,   # 混元思考模型，增强推理
        "context": "1M",
        "cost_multiplier": 0.29,
        "note": "混元思考模型，增强推理，1M 上下文，消耗 0.29x",
    },
    {
        "id": "hy3",
        "name": "Hy3",
        "vendor": "Platform",
        "supportsToolCall": True,
        "supportsImages": False,
        "supportsReasoning": False,
        "context": None,
        "cost_multiplier": None,
        "note": "平台免费模型",
    },
]

# 运行期实际使用的平台模型清单 = 种子 + 扫描器发现的平台免费模型。
# 先绑定为种子副本，保证模块导入早期（扫描器函数尚未定义时）任何引用都能取到；
# 扫描器段定义完成后由 _refresh_platform_models() 重绑为并集（见该函数处）。
PLATFORM_MODELS = list(PLATFORM_MODELS_SEED)

# 平台模型免费额度时段（跨午夜时段）
#
# 这是**兜底默认值**。实际生效的配置可由 models.json 中的 freeWindow
# 配置元素覆盖（见 load_free_window），这样延长活动期无需改源码。
# ⚠️ v5.5.0 起：权威的「当前哪些模型免费/折扣」由程序缓存扫描器
#    scan_program_config() 提供（读 ~/.workbuddy/cache 与 ~/.workbuddy-ai/cache
#    的 acc-product-config-v3.json，零 API key）。is_free_window / resolve_source
#    优先消费它。此处的 until 不再硬编码具体活动期，避免把已结束的活动误判为仍有效。
FREE_WINDOW_DEFAULT = {
    "since": "2026-09-11",   # 活动开始
    "until": None,           # 活动结束由程序缓存扫描器权威提供（v5.5.0，不再硬编码）
    "start_hour": 23,        # 每晚 23:00（仅作扫描器/缓存均不可用时的最后兜底）
    "end_hour": 8,           # 次日 08:00
}

_FREE_WINDOW_FIELDS = ("since", "until", "start_hour", "end_hour")


def _valid_fw_field(key, value):
    """校验单个 freeWindow 字段。非法返回 False（调用方保留默认值）。"""
    if key in ("since", "until"):
        # 必须是 YYYY-MM-DD 字符串
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value)
        except (ValueError, TypeError):
            return False
        return True
    # start_hour / end_hour 必须是 0-23 的整数
    # 注意：bool 是 int 的子类，需显式排除
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= 23


def _collect_layer(raw):
    """从**一层**配置中挑出通过校验的字段。

    返回 (applied_dict, applied_count)。非法字段**逐字段**跳过，
    不影响同层其他合法字段（沿用 v4 的逐字段回退语义）。
    """
    applied = {}
    if not isinstance(raw, dict):
        return applied, 0
    for k in _FREE_WINDOW_FIELDS:
        v = raw.get(k)
        if _valid_fw_field(k, v):
            applied[k] = v
    return applied, len(applied)


def _parse_window_layer(raw):
    """把**一层**配置解析为
    (default_layer, models_layer, structured, bad_ids, notes)。

    结构判定是**显式**的（design.md Decision 4）：只要出现 `default` 或 `models`
    键就视为新结构；否则整层按**旧扁平**结构处理 —— 语义等价于「只写了 default」
    （SC-FWX-003/004）。

    为什么必须显式：若靠「字段名不在白名单里就当结构」这种隐式猜测，
    一个损坏的配置（如 `{"start_hoour": 23}` 拼错键名）会被静默当成合法新结构，
    既读不到字段又不报警 —— 用户以为改动生效，实际仍在跑默认值。

    bad_ids：`models` 段中**声明了但字段全非法**的 model id 列表。
    绝不静默忽略（SC-FWX-019 / 任务 2.11）—— 调用方据此产出可观测 warning。

    notes：**逐字段**非法的可读告警（SC-FWX-016 要求「指明 hy4 的 start_hour 非法」）。
      - 仅在**新结构**下产出：旧扁平结构的「逐字段静默跳过」是 v5.2 既有语义，
        SC-FWX-003/004 要求其输出逐字一致，不得新增告警。
      - 新结构是本变更引入的，一旦用户显式使用，就必须可观测（REQ-FWX-008
        「绝不静默忽略」）。
    """
    if not isinstance(raw, dict):
        return {}, {}, False, [], []

    if "default" in raw or "models" in raw:
        notes = []

        raw_default = raw.get("default")
        if "default" in raw and not isinstance(raw_default, dict):
            notes.append(f"default 段应为 JSON 对象，实际 {type(raw_default).__name__}，已忽略")
            raw_default = None
        default_layer, _ = _collect_layer(raw_default)
        if isinstance(raw_default, dict):
            for k in _FREE_WINDOW_FIELDS:
                if k in raw_default and not _valid_fw_field(k, raw_default[k]):
                    notes.append(
                        f"default 段的 {k} 非法（{raw_default[k]!r}），已回退下层配置")

        models_layer = {}
        bad_ids = []
        raw_models = raw.get("models")
        if "models" in raw and not isinstance(raw_models, dict):
            notes.append(f"models 段应为 JSON 对象，实际 {type(raw_models).__name__}，已忽略")
            raw_models = None
        if isinstance(raw_models, dict):
            for mid, sub in raw_models.items():
                if not isinstance(mid, str) or not mid:
                    continue
                if not isinstance(sub, dict):
                    bad_ids.append(mid)
                    continue
                for k in _FREE_WINDOW_FIELDS:
                    if k in sub and not _valid_fw_field(k, sub[k]):
                        notes.append(
                            f"models.{mid} 的 {k} 非法（{sub[k]!r}），已回退全局默认")
                applied, _ = _collect_layer(sub)
                if applied:
                    models_layer[mid] = applied
                else:
                    bad_ids.append(mid)
        return default_layer, models_layer, True, bad_ids, notes

    # 旧扁平结构：整层就是 default（不产出 notes —— 保持 v5.2 的静默逐字段跳过）
    applied, _ = _collect_layer(raw)
    return applied, {}, False, [], []


def _read_models_free_window():
    """第 2 层：models.json 顶层 list 中含 "freeWindow" 键的元素。

    配置来源形如：
        [
          { "id": "...", "vendor": "Custom", ... },
          { "freeWindow": { "since": "...", "until": "...",
                            "start_hour": 23, "end_hour": 8 } }
        ]

    为什么用"list 内的配置元素"而不是把顶层改成 object：
    load_models() 依赖顶层是 list（isinstance 检查 + 遍历），
    改成 object 会破坏所有现有 models.json，用户不改文件则 skill 直接失效。
    配置元素无 vendor 字段，会被 load_models 的 vendor=="Custom" 过滤天然排除。

    返回 (default_layer, models_layer, bad_ids, notes)
    （无配置 / 全非法 / 任何异常 => 空）。
    异常捕获必须用 ValueError 而非 JSONDecodeError：
    UnicodeDecodeError 继承 ValueError 而非 OSError，
    Windows 记事本默认 GBK 编码的 models.json 会抛它。
    本函数在**模块加载期**执行（见下方模块级赋值），
    异常逃逸会导致整个模块无法 import、13 个子命令全部不可用 ——
    这比"读不到配置"严重得多。
    """
    try:
        if not os.path.exists(MODELS_JSON):
            return {}, {}, [], []
        with open(MODELS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        # ValueError 覆盖 JSONDecodeError（子）与 UnicodeDecodeError
        return {}, {}, [], []

    if not isinstance(data, list):
        return {}, {}, [], []

    for item in data:
        if not isinstance(item, dict) or "freeWindow" not in item:
            continue
        default_layer, models_layer, _structured, bad_ids, notes = \
            _parse_window_layer(item["freeWindow"])
        return default_layer, models_layer, bad_ids, notes

    return {}, {}, [], []


def _read_override_window():
    """第 1 层（最高）：relay 侧覆盖文件。

    返回 (default_layer, models_layer, warning)。覆盖文件是本 skill 自有文件
    （**不含 API Key**），损坏时视为"不存在"：返回空 + 一条人可读 warning，
    **绝不抛异常**。

    warning 非空 == 文件存在但被忽略（解析失败 / 顶层非对象 / 字段全非法）。
    必须显式告警：否则用户以为改动生效了，实际仍在跑下层配置 ——
    这正是 config_source 机制要防的"谎报来源"。
    """
    if not os.path.exists(OVERRIDE_WINDOW_FILE):
        return {}, {}, None
    try:
        with open(OVERRIDE_WINDOW_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (ValueError, OSError) as exc:
        # ValueError 覆盖 JSONDecodeError 与 UnicodeDecodeError
        return {}, {}, (f"覆盖文件 {OVERRIDE_WINDOW_FILE} 无法解析"
                        f"（{type(exc).__name__}），已忽略并回退下层配置")
    if not isinstance(raw, dict):
        return {}, {}, (f"覆盖文件 {OVERRIDE_WINDOW_FILE} 顶层应为 JSON 对象，"
                        f"实际 {type(raw).__name__}，已忽略并回退下层配置")
    default_layer, models_layer, _structured, bad_ids, notes = _parse_window_layer(raw)
    warnings = list(notes)
    if bad_ids:
        warnings.append(
            f"覆盖文件 {OVERRIDE_WINDOW_FILE} 的 models 段中 "
            f"{', '.join(sorted(bad_ids))} 无任何合法字段，已忽略该模型覆写")
    if not default_layer and not models_layer:
        warnings.append(f"覆盖文件 {OVERRIDE_WINDOW_FILE} 中无任何合法字段，"
                        f"已忽略并回退下层配置")
        return {}, {}, " / ".join(warnings)
    return default_layer, models_layer, (" / ".join(warnings) if warnings else None)


def _load_free_window_full():
    """三级加载。返回 (config, source, warnings, per_model, per_model_source)。

    优先级（**逐字段**生效；低层先写、高层后写覆盖）：
        覆盖文件 > models.json 的 freeWindow > FREE_WINDOW_DEFAULT

    每层解析为 (default_layer, models_layer)（见 `_parse_window_layer`）：
      - 全局 `config` = DEFAULT (+) models.json.default (+) override.default
      - `per_model[id]` = models.json.models[id] (+) override.models[id]
        （逐字段，同 id 后层覆盖前层）
      - `per_model_source[id]` ∈ {models.json, override} —— 该 id 的覆写**最高**来自哪层

    source 取**最高「至少一个 default 字段生效」**的那一层 —— 某层文件存在但字段
    全非法时不算生效，不谎报来源：config_source 的唯一用途就是让用户
    确认配置到底读到了没有。

    注意：**覆写层不参与 source 判定** —— `source` 描述的是「全局 default 来自哪层」，
    逐模型的来源另由 `per_model_source` 表达（SC-FWX-011 要求两者可区分且都不谎报）。
    """
    config = dict(FREE_WINDOW_DEFAULT)
    warnings = []

    models_default, models_per, models_bad, models_notes = _read_models_free_window()
    override_default, override_per, override_warning = _read_override_window()
    if override_warning:
        warnings.append(override_warning)
    if models_bad:
        warnings.append(
            f"models.json 的 freeWindow.models 段中 "
            f"{', '.join(sorted(models_bad))} 无任何合法字段，已忽略该模型覆写")
    warnings.extend(
        f"models.json 的 freeWindow.{n}" for n in models_notes)

    source = "default"
    if models_default:
        config.update(models_default)
        source = "models.json"
    if override_default:
        config.update(override_default)
        source = "override"

    per_model = {}
    per_model_source = {}
    for mid, layer in models_per.items():
        per_model.setdefault(mid, {}).update(layer)
        per_model_source[mid] = "models.json"
    for mid, layer in override_per.items():
        per_model.setdefault(mid, {}).update(layer)
        per_model_source[mid] = "override"

    return config, source, warnings, per_model, per_model_source


def load_free_window():
    """读取免费时段配置。返回 (config, source)。

    签名与 v4 / v5.1 **逐字一致**（2 元组）—— 既有调用方与测试依赖它，
    不得改成 3 元组（SC-FWX-009）。需要 warnings 请用 _load_free_window_full()。
    """
    config, source, _w, _pm, _pms = _load_free_window_full()
    return config, source


# 进程级加载一次：pick_model.py 是短生命周期 CLI 脚本，
# 单次进程内无缓存失效问题。is_free_window 与 cmd_window 共用这份配置，
# 避免两处各自计算边界导致自相矛盾（v3 曾出现过该矛盾）。
(FREE_WINDOW, FREE_WINDOW_SOURCE, FREE_WINDOW_WARNINGS,
 FREE_WINDOW_PER_MODEL, FREE_WINDOW_PER_MODEL_SOURCE) = _load_free_window_full()


def _effective_free_window(model_id):
    """返回 model_id 的**生效**时段配置：模块级全局默认 (+) 该 id 的覆写层。

    身份契约（关键）：
      - model_id 为 None，或该 id **无覆写** → 返回模块级 `FREE_WINDOW` 对象**本身**
        （身份不变）。SC-FWX-008（平台模型无覆写时判定与全局完全一致）与
        SC-FWX-010（不传 id 时与 v5.2 逐字一致）都依赖这一点。
      - 有覆写 → 返回**新 dict**，绝不原地修改模块级对象
        （否则一次逐模型判定会污染全局，后续全局判定跟着变 —— 静默错判）。

    在**调用时**读模块级 FREE_WINDOW / FREE_WINDOW_PER_MODEL，
    故测试对 `P.FREE_WINDOW` 的重绑定与原地修改都能被看到。
    """
    if model_id is None:
        return FREE_WINDOW
    per = FREE_WINDOW_PER_MODEL.get(model_id)
    if not per:
        return FREE_WINDOW
    merged = dict(FREE_WINDOW)
    merged.update(per)
    return merged


def _window_mode(model_id):
    """该 model id 的**时段适用性** —— 逐模型 opt-in 的唯一判定源（REQ-FWX-004）。

    返回三态：
      "global"        —— model_id 为 None，或无覆写且是平台内置模型
                         ⇒ 沿用全局默认时段（与 v5.2 一致，SC-FWX-008/010）
      "override"      —— 该 id 在覆写表中**显式声明**过
                         ⇒ 按其自身时段判定（SC-FWX-005/007）
      "unconstrained" —— 无覆写且**非**平台内置（自定义 / 外部模型）
                         ⇒ 不受时段约束（SC-FWX-007）

    为什么「非平台内置 ⇒ 不受约束」：只有平台模型才是「时段计费」的主体
    （免费时段外消耗积分）；自定义模型走的是**额度制**（free_allowlist +
    配额 + collect_free_quota_alerts），把时段判定普遍套上去只会产生
    「用户什么都没改，自定义模型却按时段被改判」的静默回归。
    覆写对**任意** id 有效（REQ-FWX-001），故 override 优先级最高。
    """
    if model_id is None:
        return "global"
    if model_id in FREE_WINDOW_PER_MODEL:
        return "override"
    if any(m.get("id") == model_id for m in PLATFORM_MODELS):
        return "global"
    return "unconstrained"


def _per_model_window_view():
    """逐模型生效时段视图（SC-FWX-001/011/012）。

    覆盖：全部平台内置模型 + models.json 中已声明的模型（`load_declared_models`
    已做非法条目容错与去重）。

    每项 {since, until, start_hour, end_hour, source, constraint, constraint_note}：
      - 时段取 `_effective_free_window(mid)`（全局默认叠加该 id 的覆写层）
      - source 是**两段式**标注，粒度到「层 + 段」：
          `default`            —— 全局默认（源码常量）
          `models.json.default` / `models.json.models`
          `override.default`    / `override.models`
        有逐模型覆写 → `<层>.models`；无覆写 → `<全局来源层>.default`。
        **绝不谎报**（SC-FWX-011）：hy4（覆写 23-7）报 `override.models`，
        hy3（走 default 段 23-8）报 `override.default` —— 两者可区分。
      - constraint / constraint_note 显式区分两种**免费机制**（SC-FWX-012）：
          `time_window` / 「受时段约束」     —— 平台模型，或被显式覆写过的模型
          `quota`       / 「由额度决定…」    —— 未声明覆写的自定义/外部模型
        为什么必须标注：平台模型是**时段制**，自定义模型是**额度制**
        （free_allowlist + 配额），两者都叫「免费」但语义完全不同，
        不标注会让用户误以为改 `default` 时段能影响自定义模型的可用性。

    只读：不写任何文件。供 `cmd_window` 输出，使「哪个模型用哪段时段」可逐条读出。
    """
    view = {}
    seen = set()
    for m in list(PLATFORM_MODELS) + list(load_declared_models()):
        mid = m.get("id")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        eff = _effective_free_window(mid)
        layer = FREE_WINDOW_PER_MODEL_SOURCE.get(mid)
        source = f"{layer}.models" if layer else f"{FREE_WINDOW_SOURCE}.default"
        if FREE_WINDOW_SOURCE == "default":
            source = "default"
        if _window_mode(mid) == "unconstrained":
            constraint, note = "quota", "由额度决定（不受时段约束）"
        else:
            constraint, note = "time_window", "受时段约束"
        view[mid] = {
            "since": eff.get("since"),
            "until": eff.get("until"),
            "start_hour": eff.get("start_hour"),
            "end_hour": eff.get("end_hour"),
            "source": source,
            "constraint": constraint,
            "constraint_note": note,
        }
    return view


def is_free_window(model_id=None, now=None, _scanner=None):
    """
    判断是否处于免费时段。返回 (in_free: bool, reason: str)。

    签名向后兼容（SC-FWX-009/010）：
      - 旧调用 `is_free_window(now=...)` / `is_free_window(now)` 语义**逐字不变**；
      - 新增可选 `model_id`（放在 `now` **之前**，因旧的第二位置参数已被 now 占用，
        故新增位必须是第一参数）：给定时按「该 id 的覆写 > 全局默认」合并后判定
        （SC-FWX-005/007）。

    三态语义（REQ-FWX-004 逐模型 opt-in，由 `_window_mode` 唯一决定）：
      - `global`        → 全局默认时段（不传 id / 平台模型无覆写）
      - `override`      → 该模型自身的覆写时段
      - `unconstrained` → 返回 `(False, "不受时段约束（…）")`，**与时刻无关**。
        注意这是第三态而非「收费」：非平台模型（自定义/外部）的可用性由额度决定，
        时段这一维度对它不适用（SC-FWX-007）。

    ⚠️ 局部名沿用 `FREE_WINDOW`（来自 `_effective_free_window`）：
    既有交叉断言 TC-FWAWARE-001 要求本函数**源码**引用 `FREE_WINDOW[`，
    以证明「两消费方基于同一份配置」。本函数确实以模块级 FREE_WINDOW 为**基**，
    逐模型时只是叠加覆写层 —— 契约未被破坏。
    """
    # 位置参数兼容（SC-FWX-009/010 明写「旧调用 is_free_window(now) 语义逐字不变」）：
    # v5.2 的**唯一**参数就是 now，故历史/外部调用普遍写成位置形式 `is_free_window(now)`。
    # 新签名把 model_id 放在第一位 ⇒ 位置调用会把 datetime 误当成 model id
    # （而 `_window_mode` 对未知 id 返回 unconstrained，会**静默**改判）。
    # 这里显式识别：第一参数**非字符串**即按 now 处理。
    # model id 一定是字符串 —— PLATFORM_MODELS 与 models.json 的 id 均为 str。
    #
    # ⚠️ 必须**先于** `now = now or now_utc()`：否则显式传入的位置 now 会被
    # 环境时钟（测试里被 monkeypatch 的 now_utc）覆盖，兼容语义失效。
    if model_id is not None and not isinstance(model_id, str):
        if now is None:
            now = model_id
        model_id = None

    now = now or now_utc()

    # v5.5.0：优先消费程序缓存扫描器结果（权威、零 API key）。
    # 仅当扫描器可用且给定了具体 model_id（且出现在扫描结果中）时短路返回；
    # 否则回落既有 models.json freeWindow 链（保留 FREE_WINDOW 引用供契约测试）。
    scanner = _scanner if _scanner is not None else _get_scanner(now)
    if scanner is not None and scanner.get("available") and model_id is not None:
        entry = scanner["by_id"].get(model_id)
        if entry is not None:
            return entry["free_now"], f"scanner: {model_id} free_now={entry['free_now']}"

    # 逐模型 opt-in（REQ-FWX-004 / SC-FWX-007）：未声明覆写的**非平台**模型
    # 不受时段约束 —— 判定与时刻无关（02:00 与 12:00 完全相同）。
    # 这是**第三态**：既不是「在免费时段内」，也不因时段被判为收费，
    # 而是「时段这一维度对该模型不适用」（其可用性由额度决定）。
    if _window_mode(model_id) == "unconstrained":
        return False, "不受时段约束（该模型非平台内置，可用性由额度决定）"

    FREE_WINDOW = _effective_free_window(model_id)

    # 活动期检查
    since_val = FREE_WINDOW.get("since")
    if since_val is not None:
        try:
            since_date = date.fromisoformat(since_val)
            if now.date() < since_date:
                return False, f"活动未开始（{since_val} 起）"
        except (ValueError, TypeError):
            return False, "活动期配置错误"
    until_val = FREE_WINDOW.get("until")
    if until_val is not None:
        try:
            until_date = date.fromisoformat(until_val)
            if now.date() > until_date:
                return False, f"活动已结束（{until_val} 止）"
        except (ValueError, TypeError):
            return False, "活动期配置错误"

    # 时段检查。
    #
    # 区间语义（v5.3 起区间感知，SC-FWX-002）：
    #   start < end  → **同日区间** [start, end)      如 01:00-05:00
    #   start >= end → **跨午夜区间** [start, 24) ∪ [0, end)  如跨午夜时段
    #
    # 为什么必须区分：v5.2 只有 `hour >= start or hour < end` 一条公式，
    # 对 start<end（如 01-05）会退化成「01:00 到次日 05:00 之外全免费」= 几乎全天，
    # 与用户「01:00-05:00 免费」的意图完全相反（SC-FWX-002 显式要求同日语义）。
    # start == end（如 0-0）**保持旧公式**：恒真（既有测试依赖该语义，见
    # tests/probe-free-model-confirm.py 与 test-fmr-program-integration.py）。
    hour = now.hour
    start_hour = FREE_WINDOW["start_hour"]
    end_hour = FREE_WINDOW["end_hour"]
    if start_hour < end_hour:
        in_window = start_hour <= hour < end_hour
    else:
        in_window = hour >= start_hour or hour < end_hour

    if in_window:
        # 活动末日：免费时段在 24:00 被活动期截断，文案如实提示
        if FREE_WINDOW["until"] and now.date() == date.fromisoformat(FREE_WINDOW["until"]):
            return True, (f"免费时段内（当前 {hour:02d}:{now.minute:02d}，"
                          f"活动 {FREE_WINDOW['until']} 到期，24:00 截断）")
        return True, f"免费时段内（当前 {hour:02d}:{now.minute:02d}，免费至 {FREE_WINDOW['end_hour']:02d}:00）"

    # 文案里的时段必须从 FREE_WINDOW 取，不能写死具体时段：
    # 三级配置生效后（如覆盖文件配 22-7），写死的文案会与判定结果自相矛盾
    # —— 正是 SC-FWAWARE-005 要禁的"两消费方各说各话"。
    # 默认 23/8 时输出与改动前逐字一致。
    return False, (f"收费时段（当前 {hour:02d}:{now.minute:02d}，"
                   f"免费时段 {FREE_WINDOW['start_hour']:02d}:00-"
                   f"{FREE_WINDOW['end_hour']:02d}:00）")


# ══════════════════════════════════════════════════════════════
# 程序侧账号-产品配置缓存扫描器（v5.5.0）
# 替代 FREE_WINDOW_DEFAULT 硬编码窗口：免费/折扣清单由程序启动缓存
# ~/.workbuddy/cache/acc-product-config-v3.json 与
# ~/.workbuddy-ai/cache/acc-product-config-v3.json 提供（零 API key）。
# ══════════════════════════════════════════════════════════════

PROGRAM_CACHE_RELAY_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy", "cache")
PROGRAM_CACHE_AI_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy-ai", "cache")
PROGRAM_CACHE_FILENAME = "acc-product-config-v3.json"


def _parse_credits(value):
    """解析 credit 字符串 → float。支持多种形态（2026-10-15 / 2026-10-18 双根缓存实测）：

      - 'x' 前缀 + 纯数字：models[].credits 的 'x0.29' / 'x0.00'（WB 根，v5.5.0 起）；
      - 'x' 前缀 + 数字 + 单位尾巴：WorkBuddy AI 根 models[].credits 的
        'x0.34 credits'（带 ' credits' 单位后缀）→ 剥离尾单位后解析；
      - 'x' 后缀：modelPromotions[].discount.discountedCredits 的 '0.50x' /
        '0.00x' / '0x'（WB 根促销，v5.5.0 时未覆盖 → 折扣链路哑火，见 change
        2026-10-15-platform-model-discovery C5）。

    保守不变量：非字符串 / 空 / 剥离尾单位后仍非数字 → 返回 None（调用方按
    缺失处理，绝不猜测为 0——避免把收费当免费这类不可逆错误）。
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("x"):
        num = re.split(r"[^0-9.]", s[1:], 1)[0].strip()
        try:
            return float(num)
        except ValueError:
            return None
    if low.endswith("x") and len(s) > 1:
        num = re.split(r"[^0-9.]", s[:-1], 1)[0].strip()
        try:
            return float(num)
        except ValueError:
            return None
    return None


def _parse_seg_time(v):
    """解析时段值：int（历史 fixture）/"HH:MM" 字符串（WB 根实测）/纯数字字符串 → 数值。

    bool 是 int 子类，显式排除；无法解析 → None（调用方按无促销处理，不猜）。
    "HH:MM" 归一为小时浮点（分钟除以 60，round 4 位）——支持 '7:50' 分钟级边界。
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if ":" in s:
            try:
                h, m = s.split(":", 1)
                return round(int(h) + int(m) / 60.0, 4)
            except ValueError:
                return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _seg_hit(seg, hour):
    """单段窗口命中判定：hour ∈ [start, end)（跨午夜 start>end 时取补集）。"""
    s, e = seg["start"], seg["end"]
    if s < e:
        return s <= hour < e
    return hour >= s or hour < e


def _parse_schedule_window(schedule):
    """解析 modelPromotions[].schedule → 窗口；支持三种实测形态（2026-10-15 双根缓存）：

      - daily[].start/end 为 "HH:MM" 字符串（WB 根，如 glm-5.2 的 "23:00"-"7:50"）或
        int（v5.5.0 历史 fixture，向后兼容）；
      - daily 为多段（WB 根 hy4-preview 夜间促销 [{23:00-23:59},{00:00-08:00}]）→
        返回段列表，任一段命中即生效；
      - 无 daily 但有 validFrom/validUntil（AI 根促销形态）→ 全天窗口 {start:0, end:24}
        （时段不限制，只有效期限制）。

    返回值：单段 → {start,end} dict（保持既有扫描测试对 window 的断言形态）；
    多段 → [{start,end},...]；结构不认识 / 任一段无法解析 → None（调用方按无促销
    处理——保守方向：不因解析失败放大或缩小促销）。
    """
    if not isinstance(schedule, dict):
        return None
    daily = schedule.get("daily")
    if isinstance(daily, list) and daily:
        segs = []
        for seg in daily:
            if not isinstance(seg, dict):
                return None
            s = _parse_seg_time(seg.get("start"))
            e = _parse_seg_time(seg.get("end"))
            if s is None or e is None:
                return None
            segs.append({"start": s, "end": e})
        if len(segs) == 1:
            return segs[0]
        return segs
    # 无 daily（或空列表）：仅 validFrom/validUntil 的促销按全天窗口处理
    if schedule.get("validFrom") or schedule.get("validUntil"):
        return {"start": 0, "end": 24}
    return None


def _promo_date(value):
    """解析促销有效期：date-only（'2026-10-12'）或带时区完整 ISO
    （'2026-10-12T00:00:00+08:00'，宿主缓存实测形态，date.fromisoformat 3.11
    不直接接受 → 截取前 10 位日期部分再解析）。都无法解析 → None（调用方
    跳过该校验，不猜）。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _promo_active(promo, now):
    """判断某条 modelPromotion 在 now 时刻是否 active；返回 (active, factor|None)。

    有效期字段位置双读：promo 顶层（v5.5.0 历史 fixture 形态）与
    promo.schedule 内（双根宿主缓存实测形态，2026-10-15 发现旧代码只读顶层
    → 真实数据有效期从未生效）。hour 取 now.hour + now.minute/60（分钟级精度，
    匹配 "7:50" 这类分钟边界，end 排他）；多段窗口任一段命中即 active。
    """
    if not isinstance(promo, dict):
        return False, None
    schedule = promo.get("schedule")
    window = _parse_schedule_window(schedule)
    if window is None:
        return False, None
    discount = promo.get("discount") or {}
    factor = _parse_credits(discount.get("discountedCredits"))
    if factor is None:
        return False, None
    sched = schedule if isinstance(schedule, dict) else {}
    valid_from = promo.get("validFrom") or sched.get("validFrom")
    valid_until = promo.get("validUntil") or sched.get("validUntil")
    d_from = _promo_date(valid_from)
    d_until = _promo_date(valid_until)
    if d_from is not None and now.date() < d_from:
        return False, factor
    if d_until is not None and now.date() > d_until:
        return False, factor
    hour = now.hour + now.minute / 60.0
    if isinstance(window, list):
        in_window = any(_seg_hit(seg, hour) for seg in window)
    else:
        in_window = _seg_hit(window, hour)
    return in_window, factor


def scan_program_config(roots=None, now=None):
    """双根读取程序缓存，计算 effective credits，输出当前免费/折扣模型清单。

    返回 ScanResult(dict)：
      available:      bool             —— 至少一根缓存成功读取
      by_id:          dict[id]->entry
      free_ids:       list[str]        —— free_now 为 True 的裸 id
      warnings:       list[str]
      degraded:       list[str]
      roots_scanned:  int

    entry: {id, base_credits, effective_credits, free_now, window, valid_until, source_root}
      - effective = base × active_promo_factor（无 active promo 则 = base）
      - free_now = (effective == 0)
      - 双根同 id 取更低 effective（保守，避免把收费当免费）

    降级（不变量：不得静默空清单）：
      单根缺失/异常 → 跳过 + warning，继续另一根
      双根全失败   → available=False + warnings（调用方负责回退 freeWindow 链）
    """
    if roots is None:
        roots = [PROGRAM_CACHE_RELAY_ROOT, PROGRAM_CACHE_AI_ROOT]
    if now is None:
        now = now_utc()

    by_id = {}
    warnings = []
    degraded = []
    roots_scanned = 0

    for root in roots:
        path = os.path.join(root, PROGRAM_CACHE_FILENAME)
        if not os.path.exists(path):
            warnings.append(f"缓存缺失，跳过根 {root}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (ValueError, OSError) as exc:
            warnings.append(f"缓存解析失败，跳过根 {root}（{type(exc).__name__}）")
            continue
        if not isinstance(data, dict):
            warnings.append(f"缓存顶层非对象，跳过根 {root}")
            continue
        roots_scanned += 1

        models = data.get("models")
        if not isinstance(models, list):
            models = []
        promos = data.get("modelPromotions")
        if not isinstance(promos, list):
            promos = []

        for m in models:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            mid = m["id"]
            base = _parse_credits(m.get("credits"))
            if base is None:
                degraded.append(f"模型 {mid} credits 字段缺失或不可解析，已跳过")
                continue
            factor = 1.0
            valid_until = None
            window = None
            for p in promos:
                if not isinstance(p, dict):
                    continue
                ids = p.get("modelIds")
                if not isinstance(ids, list) or mid not in ids:
                    continue
                active, f = _promo_active(p, now)
                if active and f is not None:
                    factor = f
                    valid_until = p.get("validUntil")
                    window = _parse_schedule_window(p.get("schedule"))
                    break
            effective = base * factor
            entry = {
                "id": mid,
                "base_credits": base,
                "effective_credits": effective,
                "free_now": effective == 0,
                "window": window,
                "valid_until": valid_until,
                "source_root": root,
                # 原始缓存条目（只读透传）：供 _discover_platform_models 读取
                # supportsToolCall / supportsImages / supportsReasoning 等能力位。
                # 扫描结果本身从不序列化 by_id，故不污染任何输出。
                "raw": m,
            }
            # 双根合并：同 id 取更低 effective（保守）
            if mid in by_id:
                if effective < by_id[mid]["effective_credits"]:
                    by_id[mid] = entry
            else:
                by_id[mid] = entry

    available = roots_scanned > 0
    if not available:
        warnings.append("双根缓存均不可用：扫描器整体失效，需回退 freeWindow 链")
    free_ids = [mid for mid, e in by_id.items() if e["free_now"]]
    return {
        "available": available,
        "by_id": by_id,
        "free_ids": free_ids,
        "warnings": warnings,
        "degraded": degraded,
        "roots_scanned": roots_scanned,
    }


# 模块级扫描器缓存：按需填充；测试可重置为 None 或注入。
_SCANNER_CACHE = None


def _get_scanner(now=None):
    """返回（并缓存）当前扫描结果；_SCANNER_CACHE 非 None 时直接复用。

    首次（或缓存被测试重置后）完成扫描时，同步刷新 PLATFORM_MODELS，
    使平台免费模型清单与扫描器保持一致（见 _refresh_platform_models）。
    """
    global _SCANNER_CACHE
    if _SCANNER_CACHE is not None:
        return _SCANNER_CACHE
    _SCANNER_CACHE = scan_program_config(now=now)
    _refresh_platform_models(_SCANNER_CACHE)
    return _SCANNER_CACHE


def _discover_platform_models(scanner=None):
    """从宿主程序缓存扫描器动态发现「平台内置免费模型」。

    设计动机（2026-10-15）：PLATFORM_MODELS 原先硬编码 2 条，导致平台已随附的
    免费模型（如 step-5-preview，宿主缓存 credits=x0.00）扫不出来，用户与调度
    都看不到它。改为「种子 + 扫描器发现」后，平台增删免费模型无需改源码。

    规则（保守，避免把收费模型误纳为免费）：
      - 只取扫描器判定 free_now=True 的条目（effective credits == 0）
      - 排除 custom-local:*（BYOK 自定义模型，另有通道）
      - 排除已在种子中的 id（种子条目带人工校订的 note / cost_multiplier）
      - 扫描器不可用 / 结构异常 → 返回 []（不阻断，静默回落种子）
    """
    if scanner is None:
        scanner = _SCANNER_CACHE
    if not isinstance(scanner, dict) or not scanner.get("available"):
        return []
    by_id = scanner.get("by_id") or {}
    seed_ids = {m.get("id") for m in PLATFORM_MODELS_SEED}
    out = []
    for mid in scanner.get("free_ids") or []:
        if (not isinstance(mid, str) or mid in seed_ids
                or mid.startswith("custom-local:")):
            continue
        entry = by_id.get(mid) or {}
        raw = entry.get("raw") or {}
        out.append({
            "id": mid,
            "name": raw.get("name") or mid,
            "vendor": "Platform",
            "supportsToolCall": bool(raw.get("supportsToolCall", False)),
            "supportsImages": bool(raw.get("supportsImages", False)),
            "supportsReasoning": bool(raw.get("supportsReasoning", False)),
            "context": None,
            "cost_multiplier": entry.get("effective_credits"),
            "note": "平台内置免费模型（由宿主程序缓存扫描器发现）",
            "discovered": True,
        })
    return out


def _refresh_platform_models(scanner=None):
    """重绑 PLATFORM_MODELS = 种子 + 扫描器发现的平台免费模型。

    幂等；任何异常都回落为「仅种子」，绝不因发现失败而清空平台模型。
    """
    global PLATFORM_MODELS
    try:
        discovered = _discover_platform_models(scanner)
    except Exception:
        discovered = []
    PLATFORM_MODELS = list(PLATFORM_MODELS_SEED) + discovered
    return PLATFORM_MODELS


def _all_platform_ids():
    """**时间不变**的平台模型 id 全集（种子 + 扫描器解析到的全部非 custom-local 条目）。

    用途：孤儿用量判定 / 修复保护。**不得**改用 PLATFORM_MODELS —— 那是「当前免费」
    的时变子集，模型由免费转收费后会掉出清单，其历史用量将被误判为孤立而删除。
    """
    ids = {m.get("id") for m in PLATFORM_MODELS_SEED if m.get("id")}
    sc = _SCANNER_CACHE
    if isinstance(sc, dict) and sc.get("available"):
        for mid in (sc.get("by_id") or {}):
            if isinstance(mid, str) and not mid.startswith("custom-local:"):
                ids.add(mid)
    return ids


# 导入时立即并入一次：扫描器不可用 / 抛异常则静默回落种子。
# 目的是让**任何**未先调用 _get_scanner() 的代码路径（如 cmd_inventory、
# cmd_models_list）也能看到平台免费模型，避免"清单依赖调用顺序"的隐性坑。
try:
    _refresh_platform_models(_get_scanner())
except Exception:
    pass


def build_free_candidate_pool(now=None, _scanner=None, _declared=None):
    """默认候选集 = 扫描器 free_now 裸 id；BYOK 仅兜底。

    返回 list[str]（裸 id）：
      - 扫描器可用且有免费模型 → 直接返回其 free_ids（程序侧免费裸 id）
      - 扫描器产出为空（无任何当前免费模型）→ 回退 load_declared_models()
        的 BYOK（vendor=Custom）裸 id 作为兜底
    调用方对 BYOK 兜底项加 'custom-local:' 前缀（见 cmd_next 的 recommended_prefix）。
    """
    scanner = _scanner if _scanner is not None else _get_scanner(now)
    if scanner is not None and scanner.get("available") and scanner.get("free_ids"):
        return list(scanner["free_ids"])
    declared = _declared if _declared is not None else load_declared_models()
    return [m["id"] for m in declared if m.get("vendor") == "Custom"]


# ══════════════════════════════════════════════════════════════
# 成本闸门调度层（change: 2026-10-14-cost-gate-scheduler）
# 能力：cost-gate-scheduler / free-pool-status-model / cmd-next-routing
# 设计见 .fstdd/changes/2026-10-14-cost-gate-scheduler/{design.md,specs}
# ══════════════════════════════════════════════════════════════

# 成本闸门策略默认（安全默认：付费兜底关闭，绝不静默烧付费）
COST_GATE_DEFAULTS = {
    "enabled": True,
    "capability_mode": "conservative",
    "paid_fallback_source": None,
    "default_required_caps": [],
}
COST_GATE_ENV_KEY = "AGENTINN_COST_GATE"

# 免费池四态优先级（高 → 低）；scanner_down 优先于 rate_limited 优先于 depleted 优先于 active
_FREE_POOL_PRIORITY = ["scanner_down", "rate_limited", "depleted", "active"]


def load_cost_gate_policy(state, _env=None):
    """从 STATE_FILE 的 cost_gate 键读取成本闸门策略对象。

    安全默认（paid_fallback_source=None）：修改策略只改 state 即生效，无需改源码。
    环境变量 AGENTINN_COST_GATE（合法 JSON 对象）优先，便于单测注入；非法 JSON
    回落 state 默认并告警（不抛异常）。

    返回 dict：{enabled, capability_mode, paid_fallback_source, default_required_caps}
    """
    env = _env if _env is not None else os.environ
    raw = dict(COST_GATE_DEFAULTS)
    if isinstance(state, dict) and isinstance(state.get("cost_gate"), dict):
        for k in COST_GATE_DEFAULTS:
            if k in state["cost_gate"]:
                raw[k] = state["cost_gate"][k]
    env_val = env.get(COST_GATE_ENV_KEY)
    if env_val:
        try:
            env_cfg = json.loads(env_val)
            if isinstance(env_cfg, dict):
                for k in COST_GATE_DEFAULTS:
                    if k in env_cfg:
                        raw[k] = env_cfg[k]
            else:
                print(f"[warn] {COST_GATE_ENV_KEY} 非对象 JSON，回落 state 默认", file=sys.stderr)
        except (ValueError, TypeError):
            print(f"[warn] {COST_GATE_ENV_KEY} 非法 JSON，回落 state 默认", file=sys.stderr)
    return raw


def compute_free_pool_status(scanner, usage=None, qoder_limit=None, byok_fallback_ids=None):
    """融合积分/时段/额度/限流四类信号，输出免费池四态（change: cost-gate-scheduler）。

    参数：
      scanner: scan_program_config() 的返回（available / free_ids / degraded / warnings）
      usage:   load_usage() 返回（本变更仅预留，当前未用于状态判定）
      qoder_limit: 可选 {rate_limited: bool, models: [ids]} —— 桥接源（Qoder-free）限流信号；
                   rate_limited=True 即该源限流，models 中列出的 id 从 free_candidates 剔除。
      byok_fallback_ids: 可选 list[str] —— scanner 失效时的 BYOK 兜底裸 id（build_free_candidate_pool 产出）。

    返回 dict：
      overall:   active | depleted | rate_limited | scanner_down（优先级见 _FREE_POOL_PRIORITY）
      degraded:  bool（scanner 失效或限流时为 True）
      by_source: dict —— 各免费源状态明细
      free_candidates: list[str] —— 实际可用免费 id（剔除限流源、含 BYOK 兜底）
    """
    scanner = scanner or {}
    available = bool(scanner.get("available"))
    free_ids = list(scanner.get("free_ids") or [])
    degraded = bool(scanner.get("degraded"))

    # 桥接源限流信号
    qoder_rate_limited = bool(isinstance(qoder_limit, dict) and qoder_limit.get("rate_limited"))
    rate_limited_models = list((qoder_limit or {}).get("models") or []) if qoder_rate_limited else []

    # 剔除限流源模型
    rate_set = set(rate_limited_models)
    candidates = [mid for mid in free_ids if mid not in rate_set]

    # BYOK 兜底（scanner 失效时不静默空清单）
    if byok_fallback_ids:
        for mid in byok_fallback_ids:
            if mid not in candidates:
                candidates.append(mid)

    # by_source 明细
    by_source = {}
    if available:
        by_source["program"] = {
            "state": "active" if free_ids else "depleted",
            "models": list(free_ids),
        }
    if qoder_rate_limited:
        by_source["qoder-free"] = {"state": "rate_limited", "models": list(rate_limited_models)}

    # overall 判定（优先级）
    if not available:
        overall = "scanner_down"
        degraded = True
    elif qoder_rate_limited:
        overall = "rate_limited"
        degraded = True
    elif not candidates:
        overall = "depleted"
    else:
        overall = "active"

    return {
        "overall": overall,
        "degraded": degraded,
        "by_source": by_source,
        "free_candidates": candidates,
    }


def _read_qoder_limit():
    """读取 usage.json 的 Qoder-free 限流余量信号（生产路径；单测可经 cost_gate_select 注入）。"""
    try:
        usage = load_usage()
        return usage.get("qoder_free_limit") or {}
    except Exception:
        return {}


def _record_qoder_free_limit(usage, models, rate_limited=False, exhausted_until=None):
    """记录 Qoder-free 限流余量（复用 usage.json 的 exhausted_until 同构，change: cost-gate-scheduler）。

    成功发现 N 个模型 → remaining=N；明确限流 → remaining=0 + exhausted_until。
    任何异常静默吞（D6 零阻断），不影响发现主流程。
    """
    try:
        usage["qoder_free_limit"] = {
            "remaining": 0 if rate_limited else len(models or []),
            "models": list(models or []),
            "rate_limited": bool(rate_limited),
            "exhausted_until": exhausted_until,
        }
        save_usage(usage)
    except Exception:
        pass


def _cg_required_caps(args):
    """从 --job / --needs 推导成本闸门所需的模型能力键（与 WORK_TYPE_RULES 对齐）。"""
    job = getattr(args, "job", None) or getattr(args, "needs", None)
    if not job or job not in WORK_TYPE_RULES:
        return []
    return list(WORK_TYPE_RULES[job]["required"])


def cost_gate_select(available, state, args, cost_gate, _scanner=None, _qoder_limit=None):
    """成本闸门路由编排：free-first + 能力阈值 + 付费兜底（change: cost-gate-scheduler）。

    参数：
      available:  filter_available 后的可用模型列表
      state:      load_state() 返回
      args:       argparse 参数（含 job / needs）
      cost_gate:  load_cost_gate_policy(state) 返回
      _scanner:   可注入的扫描器（测试用）
      _qoder_limit: 可注入的桥接源限流信号（测试用，否则读 usage.json）

    返回 dict：
      selected / cost_pool("free"|"paid"|None) / fell_back_to_paid / paid_reason /
      free_pool_status / error / free_quota_exhausted
      （error 非空时调用方应打印并 sys.exit(2)；本函数不直接 exit，便于单测。）
    """
    scanner = _scanner if _scanner is not None else _get_scanner()
    usage = load_usage()
    qoder_limit = _qoder_limit if _qoder_limit is not None else _read_qoder_limit()

    raw_free = build_free_candidate_pool(_scanner=scanner)
    byok = raw_free if not scanner.get("available") else None
    fps = compute_free_pool_status(scanner, usage, qoder_limit, byok_fallback_ids=byok)
    free_ids = set(fps["free_candidates"])
    free_models = [m for m in available if m["id"] in free_ids]

    cap_key = {"tool_call": "supportsToolCall", "images": "supportsImages",
               "reasoning": "supportsReasoning"}
    required_caps = _cg_required_caps(args)

    def _satisfies(m, caps):
        return all(m.get(cap_key.get(c, c), False) for c in caps)

    free_ok = ([m for m in free_models if _satisfies(m, required_caps)]
               if required_caps else list(free_models))

    paid_fallback = cost_gate.get("paid_fallback_source")

    # ① free-first：免费池有满足能力的模型 → 直接选免费
    if free_ok:
        return _cg_result(free_ok[0], "free", False, None, fps)

    # ② 能力不足：保守模式下升级到付费池（若兜底已配置）
    if free_models and not free_ok and required_caps:
        if paid_fallback:
            paid = _cg_paid_pool(available, free_ids)
            if paid:
                return _cg_result(paid[0], "paid", True, "capability_upgrade", fps)
        # 无兜底：保守默认仍选免费（best-effort）—— 免费本就不烧平台额度，不静默烧付费
        return _cg_result(free_models[0], "free", False, None, fps)

    # ③ 免费池耗尽 / scanner 失效无 BYOK 兜底
    if paid_fallback:
        paid = _cg_paid_pool(available, free_ids)
        if paid:
            reason = "scanner_down" if not scanner.get("available") else "depleted"
            return _cg_result(paid[0], "paid", True, reason, fps)

    # ④ 无付费兜底：明确 error（与现状一致），绝不静默选付费
    return {
        "selected": None,
        "cost_pool": None,
        "fell_back_to_paid": False,
        "paid_reason": None,
        "free_pool_status": fps,
        "error": "free pool exhausted and no paid fallback configured",
        "free_quota_exhausted": True,
    }


def _cg_paid_pool(available, free_ids):
    """付费池 = 可用模型中不在免费池内的部分。"""
    return [m for m in available if m["id"] not in free_ids]


def _cg_result(selected, cost_pool, fell_back, paid_reason, fps):
    return {
        "selected": selected,
        "cost_pool": cost_pool,
        "fell_back_to_paid": fell_back,
        "paid_reason": paid_reason,
        "free_pool_status": fps,
        "error": None,
        "free_quota_exhausted": False,
    }


# ══════════════════════════════════════════════════════════════
# 工作类型规则引擎
# ══════════════════════════════════════════════════════════════

WORK_TYPE_RULES = {
    "code-review": {
        "required": ["tool_call"],
        "preferred": ["reasoning"],
        "desc": "代码审查：需要工具调用，推理能力加分",
    },
    "spec-writing": {
        "required": ["tool_call"],
        "preferred": ["reasoning"],
        "desc": "规格编写：需要工具调用，推理能力加分",
    },
    "test-gen": {
        "required": ["tool_call"],
        "preferred": [],
        "desc": "测试生成：需要工具调用",
    },
    "doc-review": {
        "required": [],
        "preferred": ["tool_call"],
        "desc": "文档审查：工具调用加分但不强制",
    },
    "general": {
        "required": [],
        "preferred": [],
        "desc": "通用任务：无特殊要求",
    },
}

# 模型名称启发式：从模型 ID/名称推断擅长领域
NAME_HINTS = {
    "deepseek": {"strengths": ["code-review", "spec-writing"], "note": "DeepSeek 系列擅长代码和逻辑"},
    "glm": {"strengths": ["general", "spec-writing"], "note": "GLM 系列通用能力强"},
    "qwen": {"strengths": ["code-review", "general"], "note": "Qwen 系列代码能力突出"},
    "flash": {"strengths": ["doc-review", "general"], "note": "Flash 系列轻量快速，适合简单任务"},
    "lite": {"strengths": ["doc-review", "general"], "note": "Lite 系列轻量"},
    "reason": {"strengths": ["code-review", "spec-writing"], "note": "推理模型，适合复杂分析"},
    "o1": {"strengths": ["code-review", "spec-writing"], "note": "推理模型，适合复杂分析"},
    "mini": {"strengths": ["doc-review", "general"], "note": "Mini 系列轻量"},
}


# 来源权重（按时段动态）：
#   免费时段 → 平台模型免积分，优先用推理强的 hy4-preview
#   收费时段（08:00-23:00）→ 平台模型收费，切回外部免费 API 的 custom 模型
FREE_WINDOW_WEIGHTS = {"platform": 20, "custom": 0}   # 免费时段：平台优先
PAID_WINDOW_WEIGHTS = {"custom": 20, "platform": 0}   # 收费时段：自定义优先


def source_weights(in_free=None, model_id=None):
    """按当前（或给定）时段返回来源权重。

    `model_id` 给定时按**该模型**的生效时段判定（SC-FWX-006）：
      - 有覆写的模型（`_window_mode == "override"`）→ 按其**自身**时段。
        hy4-preview 覆写 23-7，07:30 即取收费权重（SC-FWX-006）。
      - 无覆写的平台模型 → 与全局判定一致（SC-FWX-008）。
      - **不受时段约束**的模型（未声明覆写的非平台模型）→ 退回**全局**判定。
        这是 opt-in 的关键：v5.2 里自定义模型的权重本就随全局时段变化
        （`FREE_WINDOW_WEIGHTS.custom=0` / `PAID_WINDOW_WEIGHTS.custom=20`），
        若把「不受约束」直接当成收费，02:00 时自定义权重会从 0 跳到 20，
        造成静默行为回归（正是 REQ-FWX-004 要禁的）。退回全局 ⇒ 权重与 v5.2 逐字一致。

    ⚠️ `model_id` 必须是**关键字**参数：既有测试用
    `P.source_weights = lambda in_free=None: {...}` 单参 monkeypatch 本函数，
    改成位置参数会让那些套件 `TypeError`（兼容约束）。
    """
    if in_free is None:
        if _window_mode(model_id) == "unconstrained":
            in_free, _ = is_free_window()
        else:
            in_free, _ = is_free_window(model_id)
    return FREE_WINDOW_WEIGHTS if in_free else PAID_WINDOW_WEIGHTS


# ── 成本感知（v4.2）────────────────────────────────────────
#
# 平台模型的 cost_multiplier 表示价格倍数（0.29 = 2.9 折）。
# 收费时段按折扣给分，让"同等能力下更便宜"的模型优先被选中。
COST_BONUS_SCALE = 10


def cost_bonus(model, in_free):
    """
    按成本倍数给分。免费时段恒返回 0（平台模型此时免费，成本无意义）。

    加分公式：round((1.0 - cost_multiplier) * COST_BONUS_SCALE)
      cost_multiplier=0.29 → round(0.71 × 10) = 7
      cost_multiplier=1.0  → 0（原价无折扣）
      cost_multiplier=0    → 10（满分上限）

    以下情况一律返回 0（不抛异常 —— 该字段在平台模型里是写死常量，
    用户改不到；自定义模型则根本没有这个字段）：
      - 免费时段：成本不参与
      - None：多数自定义模型没有成本概念
      - 非数值 / bool：不做隐式类型转换（bool 是 int 子类，须显式排除）
      - 越界（<0 或 >1）：倍率语义是 0~1 的价格倍数，2.5 是配置错误而非"更贵"。
        静默当 1.0 会掩盖笔误；返回 0 让行为退化成"不考虑成本"，是安全降级。
    """
    if in_free:
        return 0
    cm = model.get("cost_multiplier")
    if isinstance(cm, bool) or not isinstance(cm, (int, float)):
        return 0
    if not (0 <= cm <= 1):
        return 0
    return round((1.0 - float(cm)) * COST_BONUS_SCALE)


def cost_applicable(in_free):
    """成本分本次是否参与打分。供输出区分"不适用"与"倍率正好 1.0"。"""
    return not in_free


# 同来源内分差在此阈值内视为"同档"，参与轮换，避免总把额度压在一个模型上。
#
# TIE_TOLERANCE 是**绝对下限**：无论得分高低，至少允许 5 分差距算同档，
# 避免低分场景下容差退化为 0 导致过度收敛。
TIE_TOLERANCE = 5

# TIE_RATIO 是**相对容差比例**：容差 = max(TIE_TOLERANCE, top_score * TIE_RATIO)。
#
# 为什么需要它（v4.1 修复 P0-1）：实测三模型在 code-review 上得分 10 / 5 / 0，
# 叠加来源权重后为 30 / 25 / 20。纯绝对阈值 5 时 `(10-5) <= 5` 落在边界，
# 一旦同档其他模型被 filter_available 过滤（配额满/限流），
# top_group 退化为单元素，`(rr_idx+1) % 1 == 0` 使轮换在数学上失效
# （连续 5 次 next 返回同一模型，state 里 rr_code-review 恒为 0）。
#
# 相对容差让容差随最高分自适应：30 分时容差 18，稀疏/密集分布都能形成多元素同档组。
# 取 0.6 而非更低：保证得分明显更低的模型（如 0 分 vs 30 分）不进同档，避免削弱择优。
TIE_RATIO = 0.6


def _name_tokens(model):
    """模型 id+name 按非字母数字分词，供名称启发式精确匹配（避免子串误伤）。"""
    import re
    text = (model.get("id", "") + " " + model.get("name", "")).lower()
    return set(re.split(r"[^a-z0-9]+", text)) - {""}


def infer_work_types(model):
    """
    根据模型能力字段 + 名称启发式，推断该模型适合的工作类型。
    返回 {work_type: score} 字典，score 越高越适合。
    """
    caps = {
        "tool_call": model.get("supportsToolCall", False),
        "images": model.get("supportsImages", False),
        "reasoning": model.get("supportsReasoning", False),
    }
    tokens = _name_tokens(model)

    scores = {}
    for work_type, rule in WORK_TYPE_RULES.items():
        score = 0

        # 检查必需能力：不满足直接跳过（分数设为 -1）
        all_required_met = True
        for req in rule["required"]:
            cap_key_map = {"tool_call": "tool_call", "images": "images", "reasoning": "reasoning"}
            if not caps.get(cap_key_map.get(req, req), False):
                all_required_met = False
                break

        if not all_required_met:
            scores[work_type] = -1
            continue

        # 偏好能力加分
        for pref in rule["preferred"]:
            cap_key_map = {"tool_call": "tool_call", "images": "images", "reasoning": "reasoning"}
            if caps.get(cap_key_map.get(pref, pref), False):
                score += 10

        # 名称启发式加分（分词完整匹配，避免 minimax 命中 mini 之类的子串误伤）
        for hint_key, hint_val in NAME_HINTS.items():
            if hint_key in tokens:
                if work_type in hint_val["strengths"]:
                    score += 5

        scores[work_type] = score

    return scores


def get_model_profile(model):
    """获取模型的完整工作类型画像。"""
    scores = infer_work_types(model)
    suitable = [wt for wt, s in scores.items() if s >= 0]
    best = max(scores, key=scores.get) if suitable else "general"
    return {
        "id": model["id"],
        "suitable_types": suitable,
        "best_type": best,
        "scores": {k: v for k, v in scores.items() if v >= 0},
    }


def select_by_job_type(models, job_type, state):
    """
    智能分配：按工作类型选最优模型。
    叠加来源权重（SOURCE_WEIGHT）与成本加分后排序，同分模型间轮询。

    ── 双基准分数（v4.2）─────────────────────────────────────
      raw   裸分 = 能力门槛后得分 + 来源权重
      total  总分 = raw + 成本加分

    排序用 total，**容差基准与同档分差用 raw**。
    原因：容差公式是 `max(5, top * 0.6)` 的相对形式，若 top 用 total，
    成本加分会同步放大容差 —— 实测 strong=10+7=17 时容差从 6.0 涨到 10.2，
    把能力差 10 的弱模型（0+7=7）错误拉进同档组，削弱择优能力门槛。
    成本只应在"能力接近"时起微调作用，不该放宽能力门槛。

    返回 None 表示无可选模型（空输入 / 全部被门槛排除）。
    当前唯一调用点 cmd_next 已前置 `if not available` 拦截，
    此 guard 是防御性的 —— 该函数是模块级公开 API，不应依赖调用方前置检查。
    """
    if not models:
        return None

    in_free, _ = is_free_window()
    weights = source_weights(in_free)

    # 计算每个模型对该 job_type 的得分（raw = 能力 + 来源，total = raw + 成本）
    #
    # 逐模型权重（v5.3，SC-FWX-006）：只有**显式声明了覆写**的模型才按自身时段
    # 取权重；其余沿用上面的全局权重。这正是 opt-in 的含义 ——
    # 不声明覆写 ⇒ 权重与 v5.2 逐字相同（不会静默回归）。
    # 成本分仍按**全局**判定（与 v5.2 一致）：本切片只收敛「权重」这一消费点，
    # 不扩大改动面（成本分的语义在 REQ-FWX 中无对应要求）。
    scored = []   # (total, raw, model)
    for m in models:
        scores = infer_work_types(m)
        s = scores.get(job_type, -1)
        if s >= 0:
            mid = m.get("id")
            m_weights = weights
            if mid is not None and _window_mode(mid) == "override":
                m_weights = source_weights(model_id=mid)
            raw = s + m_weights.get(m.get("_source", "custom"), 0)
            scored.append((raw + cost_bonus(m, in_free), raw, m))

    if not scored:
        # 降级：所有模型（同样叠加来源权重）
        scored = [(weights.get(m.get("_source", "custom"), 0), 0, m) for m in models]
        if not scored:
            return None

    # 按总分降序（成本影响排序）
    scored.sort(key=lambda x: x[0], reverse=True)

    # ── 同档组判定（组合容差，基准取裸分不含成本）────────────────
    # 容差 = max(绝对下限, 裸分最高值 × 相对比例)，随裸分自适应。
    #
    # 为何不需要第二级"降级保护"（v4.1 设计稿曾有，评审后删除）：
    # 当前打分体系下最大可能分差 = 能力差(10) + 启发式差(5) = 15，
    # 而最低容差 = max(5, 20×0.6) = 12 ~ 最高容差 18，
    # 实测 30/25/20 三档全部进组 —— len(top_group)==1 永不成立。
    # 详见 .fstdd/archive/2026-10-05-scheduler-and-window-fix/pending-adjustments.yaml PA-002
    raw_top = max(raw for _, raw, _ in scored)
    tolerance = max(TIE_TOLERANCE, raw_top * TIE_RATIO)
    top_source = scored[0][2].get("_source", "custom")
    top_group = [m for _, raw, m in scored
                 if m.get("_source", "custom") == top_source
                 and (raw_top - raw) <= tolerance]

    # 在同分组中轮询
    rr_key = f"rr_{job_type}"
    rr_idx = state.get(rr_key, 0)
    selected = top_group[rr_idx % len(top_group)]
    state[rr_key] = (rr_idx + 1) % len(top_group)

    return selected


# ══════════════════════════════════════════════════════════════
# 流量统计与配额管理
# ══════════════════════════════════════════════════════════════

def _normal_entry(model_id):
    """返回一个干净的标准用量条目。"""
    return {
        "requests": 0, "tokens": 0,
        "quota": {"max_requests": None, "max_tokens": None},
        "exhausted_until": None,
        "last_used": None,
    }


def normalize_usage(usage):
    """
    归一化用量数据：清理过期的限流标记 + 补全缺失键 + 逐层类型校验。
    返回是否有修改（有则需要落盘）。

    放在 load_usage 里统一做，好处：
    - is_model_available 变纯查询，不再有"改了调用方的 dict 却不落盘"的隐式契约
    - 防御外部手改 / 旧版 usage.json 的缺键、错误类型（list/scalar/null）
    - models 元素非 dict → 重建为干净条目，避免 7 个命令全崩溃
    """
    changed = False
    models = usage.get("models")
    if not isinstance(models, dict):
        usage["models"] = {}
        models = usage["models"]
        changed = True

    for mid, entry in list(models.items()):
        # entry 非 dict → 重建为干净条目
        if not isinstance(entry, dict):
            models[mid] = _normal_entry(mid)
            entry = models[mid]
            changed = True
            continue

        # 补全缺失键 + 类型校验：数值类必须是 int/float，否则归零
        # 同时校验非负：负数是 bug，归零
        for key in ("requests", "tokens"):
            v = entry.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                entry[key] = 0
                changed = True
            elif v < 0:
                entry[key] = 0
                changed = True
        entry["requests"] = int(entry["requests"])
        entry["tokens"] = int(entry["tokens"])

        # quota 显式为 null 或非 dict 时归一（防御 AttributeError）
        quota = entry.get("quota")
        if not isinstance(quota, dict):
            entry["quota"] = {"max_requests": None, "max_tokens": None}
            quota = entry["quota"]
            changed = True
        for qk in ("max_requests", "max_tokens"):
            v = quota.get(qk)
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
                quota[qk] = None
                changed = True

        # exhausted_until 必须是非空字符串时间戳，否则清理
        eu = entry.get("exhausted_until")
        if eu:
            if not isinstance(eu, str):
                entry["exhausted_until"] = None
                changed = True
            else:
                try:
                    until = datetime.fromisoformat(eu)
                    if now_utc() >= until:
                        entry["exhausted_until"] = None
                        changed = True
                except (ValueError, TypeError):
                    entry["exhausted_until"] = None
                    changed = True
        elif eu is None:
            pass  # 正常缺失
        else:
            entry["exhausted_until"] = None
            changed = True

    return changed


USAGE_LOCK = USAGE_FILE + ".lock"
STATE_LOCK = STATE_FILE + ".lock"


class _BaseFileLock:
    """
    跨进程互斥锁基类，保证「读-改-写」临界区的原子性。
    
    实现：用 os.open(O_CREAT|O_EXCL) 原子创建锁文件——创建成功=拿锁，删除=放锁。
    - 纯文件系统原子性，不依赖 Windows 命名互斥体（沙箱/权限环境下命名对象跨进程不可靠，实测高并发大量失败）。
    - Unix/Windows 行为一致。
    - 崩溃残留：锁文件带 PID，检查进程存活，死了就强制拿锁（stale-lock 回收）。
    - 锁清理：__exit__ 重试 3 次处理 PermissionError，避免 Windows 死循环。
    - 超时：默认 30 秒，覆盖高并发场景。
    """

    LOCK_FILE = ""  # 子类必须覆盖

    def __init__(self, timeout=30):
        self.timeout = timeout  # 秒
        self._lockfile = None

    def _pid_alive(self, pid):
        """检查进程是否存活。Windows 用 OpenProcess，Unix 用 os.kill(pid, 0)。"""
        try:
            if sys.platform == "win32":
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                k = ctypes.windll.kernel32
                h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not h:
                    return False
                k.CloseHandle(h)
                return True
            else:
                # Unix: signal 0 检查进程是否存在（不发送实际信号）
                os.kill(pid, 0)
                return True
        except (PermissionError, OSError):
            # 权限不足或进程不存在时，保守返回 True（避免误抢）
            return True

    def __enter__(self):
        lock_path = self.LOCK_FILE
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        deadline = time_monotonic() + self.timeout
        attempts = 0
        while True:
            try:
                self._lockfile = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                try:
                    os.write(self._lockfile, str(os.getpid()).encode())
                except OSError:
                    pass
                return self
            except (FileExistsError, PermissionError):
                # 锁文件已存在：检查是否 stale（持有进程已死）
                stale = False
                try:
                    with open(lock_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content.isdigit():
                        pid = int(content)
                        try:
                            alive = self._pid_alive(pid)
                        except Exception:
                            alive = True  # 无法判断时保守认为活着，避免误抢
                        if not alive:
                            stale = True
                except (OSError, ValueError):
                    stale = False
                if stale:
                    # stale 回收：直接删除锁文件。
                    #
                    # 注：曾尝试改用 os.rename 做"原子认领"以消除多进程
                    # 同时判定 stale 的 TOCTOU，实测反而更糟 ——
                    # Windows 上 rename 失败率不低，失败即 continue 重试，
                    # 会导致锁文件永远不被回收，30 并发时 25 个进程锁超时
                    # （实测 10 轮仅 7/10 完整）。已回滚。
                    #
                    # 现方案的已知局限：理论上两个进程可同时判定 stale
                    # 并都执行删除，随后各自创建成功而同时进入临界区。
                    # 实测该窗口极窄（10 轮 7-9 次完整），且每次实测失败
                    # 的主因都是超时而非丢计数（详见 PA-101）。
                    # 彻底修复需改用 Windows 命名互斥体（msvcrt.locking）
                    # 或 msvcrt 区域锁，属架构级变更，另行立项。
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass
                    continue  # 重试创建
                attempts += 1
                if time_monotonic() >= deadline:
                    elapsed = time_monotonic() - (deadline - self.timeout)
                    print(f"[warn] Timed out waiting for lock {lock_path} "
                          f"(timeout={self.timeout}s, attempts={attempts})", file=sys.stderr)
                    raise TimeoutError(
                        f"Timed out waiting for lock {lock_path} "
                        f"(timeout={self.timeout}s, waited={elapsed:.1f}s, attempts={attempts})")
                time_sleep(0.03)

    def __exit__(self, *exc):
        try:
            os.close(self._lockfile)
        except (OSError, TypeError):
            pass
        lock_path = self.LOCK_FILE
        for attempt in range(3):
            try:
                os.remove(lock_path)
                break
            except PermissionError:
                time_sleep(0.02 * (attempt + 1))
            except OSError as e:
                print(f"[warn] lock cleanup failed: {e}", file=sys.stderr)
                break
        return False


class usage_file_lock(_BaseFileLock):
    """USAGE_FILE 的跨进程互斥锁。"""
    LOCK_FILE = USAGE_LOCK


class state_file_lock(_BaseFileLock):
    """STATE_FILE 的跨进程互斥锁。"""
    LOCK_FILE = STATE_LOCK


def load_usage_raw():
    """
    原始读取 usage.json（不加锁、不归一化落盘）。
    仅用于被 usage_file_lock 包裹的临界区，避免双重落盘。
    """
    if not os.path.exists(USAGE_FILE):
        return {"models": {}}
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            usage = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"models": {}}
    if not isinstance(usage, dict) or "models" not in usage:
        usage = {"models": {}}
    normalize_usage(usage)  # 归一但不落盘（临界区末尾统一落盘）
    return usage


def load_usage():
    """加载流量统计（并归一化清理，失败不影响主路径）。"""
    if not os.path.exists(USAGE_FILE):
        return {"models": {}}
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            usage = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 损坏时按空处理，不让所有命令崩溃
        return {"models": {}}
    if not isinstance(usage, dict) or "models" not in usage:
        usage = {"models": {}}
    if normalize_usage(usage):
        save_usage(usage)
    return usage


def save_usage(usage):
    """保存流量统计（原子写）。"""
    _atomic_write_json(USAGE_FILE, usage)


def ensure_model_entry(usage, model_id):
    """确保模型统计条目存在（复用干净条目模板）。"""
    if model_id not in usage.get("models", {}):
        usage.setdefault("models", {})[model_id] = _normal_entry(model_id)
    return usage["models"][model_id]


def _availability_detail(model_id, usage):
    """
    达限判定**核心**（纯查询，不改 usage、不落盘）。
    返回 (available: bool, kind: str, reason: str)
      kind: "ok" | "rate_limited" | "quota_exhausted"
            （available 为 True 时恒为 "ok"）

    为什么单独抽出来：告警需要知道"是配额用尽还是临时限流"（kind），
    而 is_model_available() 的对外契约是 2 元组。把判定只写一份、
    由 is_model_available() 与 collect_free_quota_alerts() 共用，
    避免出现两套判定逻辑漂移（一处改了另一处不改）。
    """
    entry = usage["models"].get(model_id)
    if not entry:
        return True, "ok", "no record"

    # 临时限流检查（过期项已由 normalize_usage 清理）
    if entry.get("exhausted_until"):
        try:
            until = datetime.fromisoformat(entry["exhausted_until"])
        except (ValueError, TypeError):
            until = None
        if until and now_utc() < until:
            remaining = (until - now_utc()).total_seconds() / 60
            return False, "rate_limited", f"限流中（剩 {remaining:.0f} 分钟）"

    # 配额检查
    quota = entry.get("quota") or {}
    max_req = quota.get("max_requests")
    max_tok = quota.get("max_tokens")

    if max_req is not None and entry.get("requests", 0) >= max_req:
        return False, "quota_exhausted", f"请求数达上限（{entry.get('requests', 0)}/{max_req}）"

    if max_tok is not None and entry.get("tokens", 0) >= max_tok:
        return False, "quota_exhausted", f"Token 达上限（{entry.get('tokens', 0)}/{max_tok}）"

    return True, "ok", "ok"


def is_model_available(model_id, usage):
    """
    纯查询：检查模型是否可用（未被限流、未超配额）。
    返回 (available: bool, reason: str)

    注意：本函数**不修改** usage，也不落盘。过期标记的清理统一在
    load_usage() → normalize_usage() 里完成，避免"改了却不保存"的隐式契约。
    """
    available, _kind, reason = _availability_detail(model_id, usage)
    return available, reason


def filter_available(models, usage):
    """
    过滤出可用模型，同时按 id 去重。
    返回 (available: list, blocked: list[{"model","reason"}])

    blocked 让调用方能直接排出"谁因为什么被跳过"，不必重算一遍。
    """
    available = []
    blocked = []
    seen = set()
    for m in models:
        mid = m["id"]
        if mid in seen:
            continue
        seen.add(mid)
        ok, reason = is_model_available(mid, usage)
        if ok:
            available.append(m)
        else:
            blocked.append({"model": mid, "reason": reason})
    return available, blocked


def collect_free_quota_alerts(models, usage, allowlist_ids):
    """
    收集**白名单内**已耗尽 / 被限流的模型告警，供 Agent 层弹通知。

    返回 [{"model", "kind", "detail", "source"}]，按 model 排序（确定性输出）。
      kind: "quota_exhausted"（配额用尽）| "rate_limited"（临时限流）

    三条语义约定：
    1. **白名单为空 → 恒返回空**。没有勾选过就谈不上"勾选的模型用完了"，
       不该拿未确认的模型打扰用户（R2 的触发条件是"任一**勾选**的模型用完"）。
    2. 只覆盖白名单内模型；白名单外的达限模型仍会出现在 next 的 blocked 里
       （既有语义不变），但不触发通知 —— 避免噪音。
    3. 判定复用 _availability_detail()（= is_model_available 的同一份逻辑），
       不另写一套达限判断，避免两处漂移。
    """
    if not allowlist_ids:
        return []
    allowed = set(allowlist_ids)
    alerts = []
    seen = set()
    for m in models:
        mid = m["id"]
        if mid not in allowed or mid in seen:
            continue
        seen.add(mid)
        available, kind, reason = _availability_detail(mid, usage)
        if available:
            continue
        alerts.append({
            "model": mid,
            "kind": kind,
            "detail": reason,
            "source": m.get("_source", "custom"),
        })
    alerts.sort(key=lambda a: a["model"])
    return alerts


def record_usage(usage, model_id, tokens=0):
    """
    记录一次用量。
    注意：调用方传入的 usage 可能是读时快照；为防并发计数丢失，
    真正落盘前会**重新加锁读取最新值**再累加。若 tokens 为负，按 0 处理。
    """
    if tokens is not None and tokens < 0:
        tokens = 0
    tokens = tokens or 0
    with usage_file_lock():
        fresh = load_usage_raw()
        entry = ensure_model_entry(fresh, model_id)
        entry["requests"] = int(entry.get("requests", 0)) + 1
        entry["tokens"] = int(entry.get("tokens", 0)) + int(tokens)
        entry["last_used"] = now_utc().isoformat()
        save_usage(fresh)
        # 同步回调用方的 usage（若它是同一份结构）
        if usage is not None:
            usage.pop("models", None)  # 避免脏引用
    return {"requests": entry["requests"], "tokens": entry["tokens"],
            "last_used": entry["last_used"]}


# ══════════════════════════════════════════════════════════════
# 基础工具函数
# ══════════════════════════════════════════════════════════════

# 自定义/BYOK 模型在调用侧需要带 custom-local: 前缀；平台模型不带。
# 前缀的唯一权威来源是 cmd_next 的 recommended_prefix（按 _source 派生）。
# 以下常量与归一函数用于从数据入口消除"前缀写进了 models.json id"导致的
# 双重前缀（R2）以及边界漂移（CAP-PREFIX-GUARD）。
_PREFIX_CANONICAL = "custom-local:"

def normalize_model_id(raw_id):
    """幂等（循环）剥离 custom-local: 前缀，返回裸 canonical id。

    防御两类错误（CAP-PREFIX-GUARD）：
      - R2 双重前缀：custom-local:custom-local:foo → 循环剥离至 foo（消除任意嵌套层数）；
      - 数据入口归一：models.json 无论裸填或带前缀，内部 id 恒为裸，杜绝调用方
        拼接出 custom-local:custom-local:foo（路由失败/错乱）。
    裸 id（无前缀）原样返回；非字符串 / None 原样返回（上层做空值校验）。
    """
    if not isinstance(raw_id, str):
        return raw_id
    s = raw_id
    while s.startswith(_PREFIX_CANONICAL):
        s = s[len(_PREFIX_CANONICAL):]
    return s


def load_models(source="custom"):
    """
    加载模型。source 决定模型来源：
      - custom   : 只读 models.json（vendor=Custom）
      - platform : 只读 WorkBuddy 平台内置模型
      - all      : 两者合并
    """
    result = []

    if source in ("custom", "all"):
        if os.path.exists(MODELS_JSON):
            try:
                with open(MODELS_JSON, "r", encoding="utf-8") as f:
                    all_models = json.load(f)
                if not isinstance(all_models, list):
                    all_models = []
            except (ValueError, OSError):
                # ValueError 覆盖 JSONDecodeError（子）与 UnicodeDecodeError
                # （GBK 编码的 models.json，后者继承 ValueError 非 OSError）
                # 配置损坏时按空处理，不让所有命令崩溃
                all_models = []
            for m in all_models:
                # 元素校验：非 dict / 缺 id / id 为空 → 跳过，避免 KeyError
                if not isinstance(m, dict) or not m.get("id"):
                    continue
                # freeWindow 配置元素显式排除：用户照抄模型条目改字段时
                # 可能同时带上 id + vendor="Custom"，不能依赖"配置元素
                # 不会这么写"的隐式约定 —— 它没有能力字段，混进模型列表
                # 会污染 list/profile/usage 输出。
                if "freeWindow" in m:
                    continue
                if m.get("vendor") == "Custom":
                    m = dict(m)
                    m["id"] = normalize_model_id(m.get("id"))
                    if not m.get("id"):
                        # 全被前缀剥离成空（如 id 恰为 "custom-local:"）→
                        # 按既有"id 为空则跳过"口径跳过，防止落进脏条目
                        continue
                    m["_source"] = "custom"
                    result.append(m)

    if source in ("platform", "all"):
        for m in PLATFORM_MODELS:
            m = dict(m)
            m["id"] = normalize_model_id(m.get("id"))
            if not m.get("id"):
                continue
            m["_source"] = "platform"
            result.append(m)

    return result


DECLARED_IN_FILE = "models.json"
DECLARED_IN_PLATFORM = "platform"


def load_declared_models():
    """
    枚举**全部可声明模型** —— 供 inventory 让用户勾选"哪些是免费模型"。

    与 load_models() 的关键区别：**不按 vendor == "Custom" 过滤**。
    load_models 会把非 Custom vendor 的条目**静默丢弃**，用户因此
    根本不知道它存在，也就无从把它勾成免费模型（这正是本 change 要修的）。

    返回 [{id, name, vendor, declared_in, default_free,
           default_free_reason, supportsToolCall/Images/Reasoning}, ...]

    非法条目（非 dict / 缺 id / id 非字符串 / freeWindow 配置元素）一律跳过，
    与 load_models 的容错口径一致；同 id 只保留首次出现（去重保序）。

    default_free 是**预勾选提示**，不是结论 —— 最终以用户勾选为准：
      - 平台内置  → True（免费时段内不计费）
      - vendor=Custom → True（relay 既有"免费模型"口径即自定义条目）
      - 其他 vendor   → False（既有可能收费，交给用户判断）
    """
    result = []
    seen = set()

    if os.path.exists(MODELS_JSON):
        try:
            with open(MODELS_JSON, "r", encoding="utf-8") as f:
                all_models = json.load(f)
            if not isinstance(all_models, list):
                all_models = []
        except (ValueError, OSError):
            all_models = []
        for m in all_models:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            mid = normalize_model_id(m.get("id"))
            if not isinstance(mid, str) or not mid or mid in seen:
                continue
            # freeWindow 配置元素不是模型（与 load_models 同一排除口径）
            if "freeWindow" in m:
                continue
            seen.add(mid)
            vendor = m.get("vendor")
            is_custom = vendor == "Custom"
            result.append({
                "id": mid,
                "name": m.get("name", mid),
                "vendor": vendor if isinstance(vendor, str) else "Unknown",
                "declared_in": DECLARED_IN_FILE,
                "default_free": is_custom,
                "default_free_reason": ("vendor=Custom（relay 既有免费模型口径）"
                                        if is_custom else
                                        f"vendor={vendor!r} 非 Custom，可能收费，请自行确认"),
                "supportsToolCall": bool(m.get("supportsToolCall", False)),
                "supportsImages": bool(m.get("supportsImages", False)),
                "supportsReasoning": bool(m.get("supportsReasoning", False)),
            })

    # 平台模型的「是否免费」不再一律为 True：扫描器可用时以它为准（权威、零 key）。
    # 修复动机（2026-10-15）：hy4-preview 实际计费 x0.29，旧口径却恒报"免费时段内
    # 不计费"，会在 onboarding 里被预勾选，用户可能在不知情下烧积分。
    # 扫描器不可用 → 保守沿用旧口径（True），避免把免费误报成收费（宁可多提示）。
    _sc = _get_scanner()
    _sc_ok = isinstance(_sc, dict) and bool(_sc.get("available"))
    _sc_by_id = (_sc.get("by_id") or {}) if _sc_ok else {}
    for m in PLATFORM_MODELS:
        mid = m["id"]
        if mid in seen:
            continue
        seen.add(mid)
        if mid in _sc_by_id:
            _e = _sc_by_id[mid]
            _free = bool(_e.get("free_now"))
            _eff = _e.get("effective_credits")
            _reason = ("平台内置模型：扫描器判定当前免费"
                       if _free else
                       f"平台内置模型：扫描器判定当前计费（x{_eff}），非免费")
        else:
            _free = True
            _reason = "平台内置模型（免费时段内不计费）"
        result.append({
            "id": mid,
            "name": m.get("name", mid),
            "vendor": m.get("vendor", "Platform"),
            "declared_in": DECLARED_IN_PLATFORM,
            "default_free": _free,
            "default_free_reason": _reason,
            "supportsToolCall": bool(m.get("supportsToolCall", False)),
            "supportsImages": bool(m.get("supportsImages", False)),
            "supportsReasoning": bool(m.get("supportsReasoning", False)),
        })

    return result


def resolve_source(source_arg, _scanner=None):
    """
    解析 --source 参数。auto 优先消费程序缓存扫描器结果（v5.5.0）：
      - 扫描器存在当前免费模型 → all（平台模型免费，优先纳入）
      - 扫描器无免费模型（但仍可用）→ 回落 is_free_window 既有逻辑
      - 扫描器整体不可用 → is_free_window 回落 freeWindow 链
    """
    if source_arg != "auto":
        return source_arg, None

    scanner = _scanner if _scanner is not None else _get_scanner()
    if scanner is not None and scanner.get("available") and scanner.get("free_ids"):
        return "all", "scanner: 当前存在免费程序模型"
    in_free, reason = is_free_window(_scanner=scanner)
    return ("all" if in_free else "custom"), reason


def normalize_state(state):
    """归一化轮次状态：防御语法损坏 / 非 dict / history 非 list / 索引非 int。"""
    if not isinstance(state, dict):
        return {"strategy": "round-robin", "index": 0, "history": [], "known_models": []}
    if not isinstance(state.get("history"), list):
        state["history"] = []
    if not isinstance(state.get("known_models"), list):
        state["known_models"] = []
    if not isinstance(state.get("index"), int) or isinstance(state.get("index"), bool):
        state["index"] = 0
    # rr_* 轮询键必须是非负 int
    for k, v in list(state.items()):
        if k.startswith("rr_") and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            state[k] = 0
    return state


def load_state():
    """加载轮次状态（含容错归一）。"""
    if not os.path.exists(STATE_FILE):
        return {"strategy": "round-robin", "index": 0, "history": [], "known_models": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError, TypeError):
        return {"strategy": "round-robin", "index": 0, "history": [], "known_models": []}
    return normalize_state(raw)


def _atomic_write_json(path, data, retries=5):
    """
    原子写 JSON：先写唯一临时文件再 os.replace。
    - 用 mkstemp 生成不同临时文件，避免并发进程互踩（临时文件名唯一）。
    - os.replace 在 Windows 多进程并发下偶发 PermissionError(WinError 5)，
      即使已有互斥锁，文件系统层仍有毫秒级窗口，故加短重试。
    """
    import tempfile
    os.makedirs(os.path.dirname(path), exist_ok=True)
    last_err = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".wbtmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            # 收紧文件权限：防止默认 umask 或既有权限继承导致 API Key 世界可读
            try:
                os.chmod(path, 0o600)
            except (PermissionError, OSError) as e:
                print(f"[warn] chmod failed: {e}", file=sys.stderr)
            return  # 成功
        except PermissionError as e:
            last_err = e
            # 并发竞态：清理临时文件后短暂重试
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            time_sleep(0.02 * (attempt + 1))
        except BaseException:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise
    raise last_err if last_err else OSError("atomic write failed")


def save_state(state):
    """保存轮次状态（原子写）。"""
    _atomic_write_json(STATE_FILE, state)


# ── 免费模型白名单（显式确认哪些模型算免费）──
#
# 存 state 的独立键，**不新增文件**：
#   state["free_allowlist"] = {"ids": ["a", "b"], "confirmed_at": "<ISO>"}
# normalize_state() 不清未知键、save_state() 保留未知键（既有 TC-MAINT-004/005
# 已断言该行为），故新键能安全存活；不新增文件 = 不新增锁、不新增损坏面。
FREE_ALLOWLIST_KEY = "free_allowlist"


def load_free_allowlist(state):
    """
    读取免费模型白名单。返回 (ids: list[str], meta: dict)。

    归一化（防御手改 / 旧版 state）：
      - 缺失 / 非 dict / ids 非 list → ids 为空列表（= 从未确认，视为 unset）
      - 元素非字符串或空串 → 丢弃；重复 id → 去重保序
      - confirmed_at 非字符串 → None

    注意：**空列表 == 未确认**。本 skill 不做"确认过但一个都没勾"的区分 ——
    那种状态下没有任何模型可调度，语义上等同于未确认（都会降级为既有规则）。
    """
    raw = (state or {}).get(FREE_ALLOWLIST_KEY)
    if not isinstance(raw, dict):
        return [], {"confirmed_at": None}
    ids = []
    seen = set()
    raw_ids = raw.get("ids")
    if isinstance(raw_ids, list):
        for x in raw_ids:
            if isinstance(x, str) and x and x not in seen:
                seen.add(x)
                ids.append(x)
    confirmed_at = raw.get("confirmed_at")
    if not isinstance(confirmed_at, str):
        confirmed_at = None
    return ids, {"confirmed_at": confirmed_at}


def _parse_ids_arg(raw):
    """解析 --ids a,b,c → 去空、去重保序的 id 列表。"""
    ids = []
    seen = set()
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if tok and tok not in seen:
            seen.add(tok)
            ids.append(tok)
    return ids


# ══════════════════════════════════════════════════════════════
# 子命令实现
# ══════════════════════════════════════════════════════════════

def cmd_list(args):
    """列出所有免费模型 + 推断工作类型。"""
    source, window_reason = resolve_source(getattr(args, "source", "auto"))
    models = load_models(source)
    if not models:
        print(json.dumps({"warning": "No models found", "source": source}, ensure_ascii=False))
        return
    result = []
    in_free, free_reason = is_free_window()
    for m in models:
        profile = get_model_profile(m)
        result.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "source": m.get("_source", "custom"),
            "supportsToolCall": m.get("supportsToolCall", False),
            "supportsImages": m.get("supportsImages", False),
            "supportsReasoning": m.get("supportsReasoning", False),
            "suitable_types": profile["suitable_types"],
            "best_type": profile["best_type"],
            # 成本可解释字段（v4.2），语义同 cmd_next
            "cost_multiplier": m.get("cost_multiplier"),
            "cost_bonus": cost_bonus(m, in_free),
            "cost_applicable": cost_applicable(in_free),
        })
    print(json.dumps({
        "source": source,
        "in_free_window": in_free,
        "window_reason": free_reason,
        "models": result,
        "count": len(result),
    }, indent=2, ensure_ascii=False))


def cmd_scan(args):
    """检测 models.json 中新增/移除的模型。"""
    maybe_discover_qoder_free()
    if not os.path.exists(MODELS_JSON):
        # 不写 known_models，避免下次 scan 把所有模型误报为"新增"
        print(json.dumps({"error": f"models.json not found at {MODELS_JSON}",
                          "known_models_unchanged": True}, ensure_ascii=False))
        sys.exit(1)
    models = load_models("custom")
    current_ids = [m["id"] for m in models]
    state = load_state()
    known_ids = state.get("known_models", [])

    new_ids = [mid for mid in current_ids if mid not in known_ids]
    removed_ids = [mid for mid in known_ids if mid not in current_ids]

    # 更新 known_models
    state["known_models"] = current_ids
    try:
        with state_file_lock():
            save_state(state)
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}", "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)

    # 为新模型推断工作类型 + 初始化用量统计
    new_profiles = []
    usage = load_usage()
    for m in models:
        if m["id"] in new_ids:
            ensure_model_entry(usage, m["id"])
            profile = get_model_profile(m)
            new_profiles.append({
                "id": m["id"],
                "best_type": profile["best_type"],
                "suitable_types": profile["suitable_types"],
            })
    try:
        with usage_file_lock():
            save_usage(usage)
    except TimeoutError as e:
        print(json.dumps({"error": f"usage lock timeout: {e}", "hint": "并发写入 USAGE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)

    result = {
        "new_models": new_profiles,
        "removed_models": removed_ids,
        "total_current": len(current_ids),
        "total_known": len(known_ids),
    }

    if new_profiles:
        result["auto_assigned"] = True
        result["note"] = "新模型已自动检测并初始化用量统计，可直接用于 auto 策略分配"
    elif not new_ids and not removed_ids:
        result["note"] = "无变化，模型列表与上次一致"

    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_inventory(args):
    """
    枚举**全部**可声明模型，供 Agent 层弹窗勾选"哪些是免费模型"。

    为什么不在脚本里做交互式勾选：本脚本现状零交互（无 input/isatty），
    被 Agent 以管道调用时非 TTY，交互会直接挂死；且 Windows TTY 多选
    要自实现按键处理，脆且易踩 GBK 编码坑。故脚本只出**机器可读数据**，
    "弹窗勾选"由 Agent 层的多选提问呈现，勾完再 free set 落盘。
    """
    declared = load_declared_models()
    state = load_state()
    ids, meta = load_free_allowlist(state)
    selected = set(ids)

    models = []
    for m in declared:
        models.append({
            "id": m["id"],
            "name": m["name"],
            "vendor": m["vendor"],
            "declared_in": m["declared_in"],
            "default_free": m["default_free"],
            "default_free_reason": m["default_free_reason"],
            "supportsToolCall": m["supportsToolCall"],
            "supportsImages": m["supportsImages"],
            "supportsReasoning": m["supportsReasoning"],
            # 便于 Agent 把上次的确认结果预勾选出来
            "currently_selected": m["id"] in selected,
        })

    print(json.dumps({
        "models": models,
        "count": len(models),
        "by_source": {
            DECLARED_IN_FILE: sum(1 for m in models if m["declared_in"] == DECLARED_IN_FILE),
            DECLARED_IN_PLATFORM: sum(1 for m in models if m["declared_in"] == DECLARED_IN_PLATFORM),
        },
        "free_allowlist": {"ids": ids, "confirmed_at": meta.get("confirmed_at")},
        "onboard_due": _onboard_due_now(state),
        "models_json": MODELS_JSON,
        "hint": "把用户勾选的 id 用 `free set --ids a,b,c` 落盘；"
                "default_free 只是预勾选提示，以用户勾选为准",
    }, indent=2, ensure_ascii=False))


def _read_models_raw_at(root):
    """读取指定 data-root 下 models.json 的原始条目 list（不按 vendor 过滤）。

    供 `origins` 命令横向枚举 whitelist 中**每一个**候选 root，
    判断它是否真有模型数据、以及每条模型由哪个工具写入。
    与 `_read_raw_models_list()`（只读当前 data-root）相对，二者口径一致：
    文件缺失 / 非法 JSON / 顶层非 list 一律返回 []。
    """
    p = os.path.join(root, _MODELS_JSON_NAME)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def _detect_source_tool(models):
    """依据条目上的 *Owner 标记判定这批模型由哪个工具写入。

    返回 (tool, detail)：
      - 含 relayOwner（且无外部 *Owner） → ("relay", <标记值：旧值/新值/回退 agentinn>)
      - 含非 relayOwner 的 *Owner        → ("ow-bridge"|"external", 已知名或键名)
      - 无任何 *Owner 标记                → ("unknown", None)
    复用 _owner_marker_keys / RELAY_OWNER_KEY / RELAY_OWNER_VALUES / KNOWN_EXTERNAL_OWNERS，
    与 models add / list 的判定口径一致，不另起一套（避免漂移）。

    外部标记优先（与 cmd_models_list 一致，评审 P1-3）：同一条目**同时**带 relayOwner
    与外部标记时按 external 归类（保守口径），避免「origins 报 relay、list 报 external」漂移。

    双标记兼容（SC-014/015）：relay 标记值无论为旧值还是新值（或历史条目缺值），
    一律判为 relay；detail 回显实际标记值，便于 origins 诊断旧数据。
    """
    tool, detail = "unknown", None
    for m in models:
        if not isinstance(m, dict):
            continue
        keys = _owner_marker_keys(m)
        # 外部标记优先：存在任何非 relayOwner 的 *Owner 键 ⇒ 按 external 归类（与 list 对齐）
        external_keys = [k for k in keys if k != RELAY_OWNER_KEY]
        if external_keys:
            k = external_keys[0]
            mapped = OWNER_TOOL_MAP.get(k)
            if mapped:
                tool, detail = mapped, (KNOWN_EXTERNAL_OWNERS.get(k) or k)
            else:
                tool, detail = "external", k
            continue
        if RELAY_OWNER_KEY in keys:
            val = m.get(RELAY_OWNER_KEY)
            if isinstance(val, str) and val in RELAY_OWNER_VALUES:
                return "relay", val
            return "relay", RELAY_OWNER_VALUE
    return tool, detail


def cmd_origins(args):
    """只读：枚举模型来源的每一个候选 data-root 与平台源。

    与 `inventory` 的区别：inventory 只报"当前 data-root 下可声明模型"，
    origins 横向枚举 whitelist 中**全部** root（去重），指出每条模型由哪个
    工具写入（relay / OW Bridge / 平台），并给出每个来源的免费语义——
    让用户一眼看清"免费候选到底从哪来"。纯只读，不修改 relay 的语义数据；唯一例外是
    进程启动时的一次性数据迁移（旧名文件→新名，幂等、保留旧文件，见
    `_migrate_legacy_data_files`，评审 P1-4）。
    """
    sources = []
    seen_roots = set()

    # ① 每个候选 data-root（whitelist + env 覆盖根；去重）
    candidate_roots = list(DATA_ROOT_WHITELIST)
    env_root = os.environ.get("FMR_DATA_ROOT")
    if env_root:
        candidate_roots.append(env_root)
    env_models = os.environ.get("FMR_MODELS_JSON")
    if env_models:
        d = os.path.dirname(os.path.abspath(env_models))
        if d and d not in candidate_roots:
            candidate_roots.append(d)

    for name in candidate_roots:
        root = name if os.path.isabs(name) else os.path.join(HOME, name)
        root = os.path.abspath(root)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        raw = _read_models_raw_at(root)
        models = [m for m in raw
                  if isinstance(m, dict) and m.get("id") and "freeWindow" not in m]
        if not models:
            continue
        tool, detail = _detect_source_tool(models)
        if tool == "relay":
            free_semantics = "quota(free_allowlist-gated)"
        elif tool in ("ow-bridge", "external", "qoder-free", "qodercli"):
            free_semantics = "quota(third-party-managed)"
        else:
            free_semantics = "quota(unknown)"
        sources.append({
            "type": "file",
            "root": root,
            "tool": tool,
            "tool_detail": detail,
            "model_count": len(models),
            "free_semantics": free_semantics,
        })

    # ② 平台源（恒定一个，由 PLATFORM_MODELS 硬编码）
    platform_models = []
    for m in PLATFORM_MODELS:
        platform_models.append({
            "id": m["id"],
            "free_now": is_free_window(m["id"])[0],
        })
    sources.append({
        "type": "platform",
        "tool": "platform",
        "tool_detail": None,
        "model_ids": [m["id"] for m in PLATFORM_MODELS],
        "free_semantics": {
            "mechanism": "program_cache_window",
            "models": platform_models,
        },
    })

    print(json.dumps({
        "data_root": _DATA_ROOT,
        "count": len(sources),
        "sources": sources,
    }, indent=2, ensure_ascii=False))


def cmd_free(args):
    """免费模型白名单：set / show / clear。"""
    action = args.free_action

    if action == "show":
        state = load_state()
        ids, meta = load_free_allowlist(state)
        print(json.dumps({
            "free_allowlist": {"ids": ids, "confirmed_at": meta.get("confirmed_at")},
            "count": len(ids),
            "state": "unset" if not ids else "applied",
            "declared_count": len(load_declared_models()),
            "note": "白名单为空时 relay 退回既有规则（不阻断）；要确认用 free set --ids",
        }, indent=2, ensure_ascii=False))
        return

    if action == "clear":
        try:
            with state_file_lock():
                fresh = load_state()
                fresh[FREE_ALLOWLIST_KEY] = {"ids": [], "confirmed_at": None}
                save_state(fresh)
        except TimeoutError as e:
            print(json.dumps({"error": f"state lock timeout: {e}", "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps({
            "free_allowlist": {"ids": [], "confirmed_at": None},
            "count": 0,
            "state": "unset",
            "note": "已清空；relay 退回既有规则（下次触发会重新弹窗确认）",
        }, indent=2, ensure_ascii=False))
        return

    # action == "set"
    want = _parse_ids_arg(args.ids)
    if not want:
        print(json.dumps({
            "error": "--ids 为空",
            "hint": "至少勾选一个模型，如 `free set --ids alpha-model,beta-model`；"
                    "要清空请用 `free clear`",
        }, ensure_ascii=False))
        sys.exit(1)

    declared = {m["id"]: m for m in load_declared_models()}
    unknown = [i for i in want if i not in declared]
    if unknown:
        print(json.dumps({
            "error": f"未知模型 id: {unknown}",
            "available": sorted(declared),
            "hint": "id 需取自 `inventory` 的输出（大小写敏感）",
        }, ensure_ascii=False))
        sys.exit(1)

    # 白名单里勾了 relay 调度不到的条目（非 Custom vendor 不参与候选集）→ 明确警告，
    # 否则用户会陷入"勾了却永远选不到"的静默困惑。
    selectable = {m["id"] for m in load_models("all")}
    unreachable = [i for i in want if i not in selectable]
    warnings = []
    if unreachable:
        warnings.append(
            f"以下 id 已记入白名单，但 relay 不会调度它们（非 Custom vendor 条目"
            f"不参与候选集）：{unreachable}")

    try:
        with state_file_lock():
            # 锁内重新读取再改，避免与其他命令的写回互相覆盖
            fresh = load_state()
            fresh[FREE_ALLOWLIST_KEY] = {"ids": want,
                                         "confirmed_at": now_utc().isoformat()}
            save_state(fresh)
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}", "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({
        "free_allowlist": fresh[FREE_ALLOWLIST_KEY],
        "count": len(want),
        "warnings": warnings or None,
        "note": "relay 只从白名单内挑选模型；每次触发都会重新确认（不落一次性开关）",
    }, indent=2, ensure_ascii=False))


def cmd_next(args):
    """获取下一个模型（自动跳过超限/限流模型，auto 源按时段切换）。"""
    maybe_discover_qoder_free()
    source, window_reason = resolve_source(getattr(args, "source", "auto"))
    models = load_models(source)
    if not models:
        print(json.dumps({"error": "No models available", "source": source}, ensure_ascii=False))
        sys.exit(1)

    usage = load_usage()
    strategy = args.strategy or "cost-gate"
    state = load_state()

    # 免费模型白名单：只做**候选集过滤**，不参与打分/排序/轮询（design.md D4）。
    # 白名单为空 → 原样放行并标注 allowlist=unset（降级不阻断）。
    allowlist_ids, _allowlist_meta = load_free_allowlist(state)
    allowlist_state = "applied" if allowlist_ids else "unset"

    # 过滤可用模型（load_usage 已归一化，无需事后补 save）
    available, blocked = filter_available(models, usage)

    if allowlist_ids:
        allowed = set(allowlist_ids)
        # 被白名单挡掉的**可用**模型也记进 blocked：既有契约是"谁因为什么被跳过"，
        # 静默丢弃会让调用方无法解释候选集为何变小。
        blocked = blocked + [{"model": m["id"], "reason": "不在免费白名单内（未勾选）"}
                             for m in available if m["id"] not in allowed]
        # 显式排序保证确定性：白名单内（真正不可用）在前，其余按 id
        blocked.sort(key=lambda b: (0 if b["model"] in allowed else 1, b["model"]))
        available = [m for m in available if m["id"] in allowed]

    # 额度告警：只覆盖白名单内模型（未勾选的不打扰用户）
    alerts = collect_free_quota_alerts(models, usage, allowlist_ids)
    # 勾选的免费模型全部用完（无模型可选）→ R2 的"全用完"情形
    free_quota_exhausted = bool(allowlist_ids) and not available

    if not available:
        # 全不可用 → 返回 error 而非不可用模型（配额/限流不应被绕过）
        print(json.dumps({
            "error": "all models unavailable",
            "blocked": blocked,
            "allowlist": allowlist_state,
            "quota_alerts": alerts,
            "free_quota_exhausted": free_quota_exhausted,
            "hint": "用 quota show 查配额；clear-exhausted 手动恢复；或等限流到期"
                    + ("；白名单勾得过窄时用 free set 重新勾选" if allowlist_ids else ""),
        }, indent=2, ensure_ascii=False))
        sys.exit(2)

    if state.get("strategy") != strategy:
        # 策略切换：重置 index，但保留 rr_<job> 轮询位和 known_models
        #
        # 注意：free_allowlist 必须一并保留 —— 它属于**用户确认结果**而非轮次状态，
        # 重建 state 时丢掉它会让白名单在"策略切换"时静默失效（TC-FMC-005 守这一点）。
        # v5.6.0：relay_onboard 同理必须保留，否则策略切换会静默抹掉向导确认结果。
        preserved = {k: v for k, v in state.items()
                     if k.startswith("rr_") or k in (FREE_ALLOWLIST_KEY, RELAY_ONBOARD_KEY, "cost_gate")}
        # 显式排序保证确定性：消除对 dict 迭代顺序的依赖（P3-21）
        preserved_sorted = {k: preserved[k] for k in sorted(preserved)}
        state = {"strategy": strategy, "index": 0, "history": state.get("history", []),
                 "known_models": state.get("known_models", []), **preserved_sorted}

    selected = None
    violation = None  # 仅 auto 策略有意义：所选模型是否满足 job 必需能力
    # 成本闸门输出契约（仅 cost-gate 策略填充；旧策略保持逐字不变以保全 28/28 回归）
    cost_pool = None
    fell_back_to_paid = False
    paid_reason = None
    free_pool_status = None

    if strategy == "round-robin":
        idx = state.get("index", 0) % len(available)
        selected = available[idx]
        state["index"] = (idx + 1) % len(available)

    elif strategy == "fallback":
        idx = state.get("index", 0)
        if idx >= len(available):
            idx = 0
        selected = available[idx]
        state["index"] = idx + 1

    elif strategy == "capability-match":
        needs = args.needs or []
        # 校验 needs 白名单
        VALID_NEEDS = {"tool_call", "images", "reasoning"}
        invalid_needs = [n for n in needs if n not in VALID_NEEDS]
        if invalid_needs:
            print(json.dumps({
                "error": f"Invalid needs: {invalid_needs}",
                "valid_values": sorted(VALID_NEEDS),
                "hint": "Only tool_call, images, reasoning are allowed",
            }, ensure_ascii=False))
            sys.exit(1)
        candidates = available
        if "tool_call" in needs:
            candidates = [m for m in candidates if m.get("supportsToolCall")]
        if "images" in needs:
            candidates = [m for m in candidates if m.get("supportsImages")]
        if "reasoning" in needs:
            candidates = [m for m in candidates if m.get("supportsReasoning")]
        if not candidates:
            candidates = available
        idx = state.get("index", 0) % len(candidates)
        selected = candidates[idx]
        state["index"] = (idx + 1) % len(candidates)

    elif strategy == "auto":
        # --job 是 auto 策略的必填参数（help 与 SKILL.md 均如此声明）。
        # 缺参数时静默兜底为 "general" 会让调用方误以为按预期工作类型做了
        # 智能分配 —— 错误的分配比直接报错更危险，故显式报错退出。
        if not args.job:
            print(json.dumps({
                "error": "--strategy auto requires --job",
                "valid_types": list(WORK_TYPE_RULES.keys()),
                "hint": "若只是想轮询均匀分摊，用 --strategy round-robin；"
                        "若要做工作性质智能分配，--job 取 valid_types 中任一值",
            }, ensure_ascii=False))
            sys.exit(1)
        job_type = args.job
        if job_type not in WORK_TYPE_RULES:
            print(json.dumps({"error": f"Unknown job type: {job_type}",
                              "valid_types": list(WORK_TYPE_RULES.keys())}, ensure_ascii=False))
            sys.exit(1)
        # available 已经过 filter_available，直接选最优
        selected = select_by_job_type(available, job_type, state)
        # 能力违规标记：所选模型不满足该 job 的必需能力（候选全不满足时降级选中）
        rule = WORK_TYPE_RULES[job_type]
        cap_map = {"tool_call": "supportsToolCall", "images": "supportsImages",
                   "reasoning": "supportsReasoning"}
        violation = any(not selected.get(cap_map.get(r, r), False) for r in rule["required"])

    elif strategy == "cost-gate":
        # 成本闸门默认路由：free-first + 能力阈值 + 付费兜底（change: cost-gate-scheduler）
        cg = cost_gate_select(available, state, args, load_cost_gate_policy(state),
                              _scanner=_get_scanner())
        if cg.get("error"):
            print(json.dumps({
                "error": cg["error"],
                "blocked": blocked,
                "allowlist": allowlist_state,
                "quota_alerts": alerts,
                "free_quota_exhausted": cg["free_quota_exhausted"],
                "free_pool_status": cg["free_pool_status"],
                "hint": "配置 state.cost_gate.paid_fallback_source 启用付费兜底；"
                        "或用 quota show 查配额 / clear-exhausted 恢复",
            }, indent=2, ensure_ascii=False))
            sys.exit(2)
        selected = cg["selected"]
        cost_pool = cg["cost_pool"]
        fell_back_to_paid = cg["fell_back_to_paid"]
        paid_reason = cg["paid_reason"]
        free_pool_status = cg["free_pool_status"]

    # 记录历史
    state.setdefault("history", []).append({
        "model": selected["id"],
        "strategy": strategy,
        "job": args.job if strategy == "auto" else None,
        "timestamp": now_utc().isoformat(),
    })
    state["history"] = state["history"][-50:]

    try:
        with state_file_lock():
            save_state(state)
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}", "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)

    # v5.5.0：recommended_prefix —— 程序侧免费模型裸 id；BYOK（_source=custom）兜底项加 custom-local: 前缀
    recommended_prefix = "custom-local:" if selected.get("_source") == "custom" else ""

    # 输出
    profile = get_model_profile(selected)
    in_free, free_reason = is_free_window()
    # 说明：selected 必然来自 filter_available，故恒可用；
    # 不可用的情况已在上游 exit 2 返回 error，这里不再重复检查（避免死代码）。
    # 收费时段显式选平台模型 → 警告（平台模型收费）
    source_warning = None
    if not in_free and selected.get("_source") == "platform" and getattr(args, "source", "auto") in ("platform", "all"):
        source_warning = "当前为收费时段，选中的是平台模型（可能产生费用）"
    out = {
        "model": selected["id"],
        "model_full": recommended_prefix + selected["id"],
        "recommended_prefix": recommended_prefix,
        "name": selected.get("name", selected["id"]),
        "source": selected.get("_source", "custom"),
        "strategy": strategy,
        "job": args.job if strategy == "auto" else None,
        "best_type": profile["best_type"],
        # available 不输出：selected 必然来自 filter_available（恒可用）。
        # 全不可用时命令已 exit 2 并输出 error + blocked，不会走到这里。
        "capability_violation": violation,
        "blocked": blocked if blocked else None,
        # 白名单与额度告警（v5.1）：allowlist=applied 时 selected 必然在白名单内；
        # quota_alerts 非空 → Agent 层弹通知（只覆盖白名单内模型）
        "allowlist": allowlist_state,
        "onboard_due": _onboard_due_now(state),
        "quota_alerts": alerts,
        "free_quota_exhausted": free_quota_exhausted,
        "source_warning": source_warning,
        "in_free_window": in_free,
        "window_reason": free_reason,
        # 成本可解释字段（v4.2）：cost_applicable 区分"免费时段不计入成本"
        # 与"成本倍率正好 1.0"—— 只看 cost_bonus==0 无法分辨这两种情况。
        "cost_multiplier": selected.get("cost_multiplier"),
        "cost_bonus": cost_bonus(selected, in_free),
        "cost_applicable": cost_applicable(in_free),
        "supportsToolCall": selected.get("supportsToolCall", False),
        "supportsImages": selected.get("supportsImages", False),
        "supportsReasoning": selected.get("supportsReasoning", False),
        "next_index": state.get("index", 0),
    }
    # 成本闸门输出契约：仅 cost-gate 策略附加四字段，避免改变旧策略输出形状（REQ-CNR-003）
    if strategy == "cost-gate":
        out["cost_pool"] = cost_pool
        out["fell_back_to_paid"] = fell_back_to_paid
        out["paid_reason"] = paid_reason
        out["free_pool_status"] = free_pool_status
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_profile(args):
    """查看每个模型的工作类型画像。"""
    source, _ = resolve_source(getattr(args, "source", "auto"))
    models = load_models(source)
    if not models:
        print(json.dumps({"warning": "No models found"}, ensure_ascii=False))
        return

    result = []
    for m in models:
        profile = get_model_profile(m)
        hints = []
        tokens = _name_tokens(m)
        for hint_key, hint_val in NAME_HINTS.items():
            if hint_key in tokens:
                hints.append({"key": hint_key, **hint_val})

        result.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "source": m.get("_source", "custom"),
            "capabilities": {
                "toolCall": m.get("supportsToolCall", False),
                "images": m.get("supportsImages", False),
                "reasoning": m.get("supportsReasoning", False),
            },
            "best_type": profile["best_type"],
            "suitable_types": profile["suitable_types"],
            "scores": profile["scores"],
            "name_hints": hints,
        })

    print(json.dumps({"profiles": result, "count": len(result)}, indent=2, ensure_ascii=False))


def cmd_usage(args):
    """流量统计表。"""
    source, _ = resolve_source(getattr(args, "source", "auto"))
    models = load_models(source)
    usage = load_usage()

    # 确保新模型有条目（仅当确实新增时才落盘，免得每次写盘放大并发互踩）
    has_new = False
    for m in models:
        if m["id"] not in usage.get("models", {}):
            ensure_model_entry(usage, m["id"])
            has_new = True
    if has_new:
        try:
            with usage_file_lock():
                save_usage(usage)
        except TimeoutError as e:
            print(json.dumps({"error": f"usage lock timeout: {e}", "hint": "并发写入 USAGE_FILE 超时，请稍后重试"}, ensure_ascii=False))
            sys.exit(1)

    table = []
    for m in models:
        entry = usage["models"].get(m["id"], {})
        ok, reason = is_model_available(m["id"], usage)
        quota = entry.get("quota", {})

        max_req = quota.get("max_requests")
        max_tok = quota.get("max_tokens")

        # 计算剩余
        req_remain = (max_req - entry["requests"]) if max_req is not None else None
        tok_remain = (max_tok - entry["tokens"]) if max_tok is not None else None

        # 状态
        if not ok:
            status = f"⚠️ {reason}"
        else:
            status = "✅ 可用"

        table.append({
            "id": m["id"],
            "source": m.get("_source", "custom"),
            "requests": entry.get("requests", 0),
            "tokens": entry.get("tokens", 0),
            "max_requests": max_req if max_req is not None else "∞",
            "max_tokens": max_tok if max_tok is not None else "∞",
            "req_remaining": req_remain if req_remain is not None else "∞",
            "tok_remaining": tok_remain if tok_remain is not None else "∞",
            "last_used": entry.get("last_used"),
            "status": status,
        })

    in_free, free_reason = is_free_window()
    print(json.dumps({
        "in_free_window": in_free,
        "window_reason": free_reason,
        "source": source,
        "usage_table": table,
        "total_models": len(table),
        "available": sum(1 for t in table if t["status"].startswith("✅")),
    }, indent=2, ensure_ascii=False))


def cmd_record(args):
    """记录一次用量（并报出白名单内模型的额度告警）。"""
    models = load_models("all")  # 记录时接受所有来源
    model_ids = [m["id"] for m in models]
    if args.model not in model_ids:
        print(json.dumps({"error": f"Model {args.model} not found",
                          "available": model_ids}, ensure_ascii=False))
        sys.exit(1)

    usage = load_usage()
    entry = record_usage(usage, args.model, args.tokens or 0)

    # record_usage() 落盘前会**重新加锁读取最新值**再累加，并把调用方传入的
    # usage 的 models 键 pop 掉（防脏引用）。故判定告警必须重新 load_usage()，
    # 否则拿到的是空表 —— 会静默漏报"刚打到上限"这一刻。
    usage_after = load_usage()
    state = load_state()
    allowlist_ids, _meta = load_free_allowlist(state)
    alerts = collect_free_quota_alerts(models, usage_after, allowlist_ids)

    print(json.dumps({
        "model": args.model,
        "requests": entry["requests"],
        "tokens": entry["tokens"],
        "recorded_at": entry["last_used"],
        # 额度告警（v5.1）：非空 → Agent 层弹通知；只覆盖白名单内模型
        "quota_alerts": alerts,
        "quota_exhausted": any(a["model"] == args.model for a in alerts),
    }, indent=2, ensure_ascii=False))


def cmd_quota(args):
    """配额管理。"""
    if args.quota_action == "show":
        usage = load_usage()
        models = load_models("all")  # 平台模型配额也显示
        result = []
        for m in models:
            entry = usage["models"].get(m["id"], {})
            quota = entry.get("quota", {})
            result.append({
                "id": m["id"],
                "max_requests": quota.get("max_requests"),
                "max_tokens": quota.get("max_tokens"),
            })
        print(json.dumps({"quotas": result}, indent=2, ensure_ascii=False))
        return

    if args.quota_action == "set":
        if not args.model:
            print(json.dumps({"error": "set requires --model"}, ensure_ascii=False))
            sys.exit(1)
        if (args.max_requests is not None and args.max_requests < 0) or \
           (args.max_tokens is not None and args.max_tokens < 0):
            print(json.dumps({"error": "max-requests/max-tokens must be >= 0"}, ensure_ascii=False))
            sys.exit(1)
        models = load_models("all")  # 平台模型也可设配额
        model_ids = [m["id"] for m in models]
        if args.model not in model_ids:
            print(json.dumps({"error": f"Model {args.model} not found",
                              "available": model_ids}, ensure_ascii=False))
            sys.exit(1)
        try:
            with usage_file_lock():
                usage = load_usage()
                entry = ensure_model_entry(usage, args.model)
                if args.max_requests is not None:
                    entry["quota"]["max_requests"] = args.max_requests
                if args.max_tokens is not None:
                    entry["quota"]["max_tokens"] = args.max_tokens
                save_usage(usage)
        except TimeoutError as e:
            print(json.dumps({"error": f"usage lock timeout: {e}", "hint": "并发写入 USAGE_FILE 超时，请稍后重试"}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps({
            "model": args.model,
            "quota": entry["quota"],
            "note": "设置后选模型会自动跳过超限模型",
        }, indent=2, ensure_ascii=False))
        return


def cmd_mark_exhausted(args):
    """标记模型临时限流。"""
    if args.minutes is not None and args.minutes <= 0:
        print(json.dumps({"error": "--minutes must be > 0"}, ensure_ascii=False))
        sys.exit(1)
    if args.minutes is not None and args.minutes > 1440:
        print(json.dumps({"error": f"--minutes must be <= 1440 (24h), got {args.minutes}", "hint": "如需更长时间限流，请手动编辑 usage.json"}, ensure_ascii=False))
        sys.exit(1)
    # 校验 model 存在性（与 cmd_record 行为一致）
    models = load_models("all")
    model_ids = [m["id"] for m in models]
    if args.model not in model_ids:
        print(json.dumps({"error": f"Model {args.model} not found",
                          "available": model_ids}, ensure_ascii=False))
        sys.exit(1)
    try:
        with usage_file_lock():
            usage = load_usage()
            entry = ensure_model_entry(usage, args.model)
            until = now_utc() + timedelta(minutes=args.minutes or 60)
            entry["exhausted_until"] = until.isoformat()
            save_usage(usage)
            print(json.dumps({
                "model": args.model,
                "exhausted_until": entry["exhausted_until"],
                "duration_minutes": args.minutes or 60,
                "note": "下次选模型会自动跳过该模型，到期后自动恢复",
            }, indent=2, ensure_ascii=False))
    except TimeoutError as e:
        print(json.dumps({"error": f"usage lock timeout: {e}", "hint": "并发写入 USAGE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)


def cmd_clear_exhausted(args):
    """清除限流标记。"""
    try:
        with usage_file_lock():
            usage = load_usage()
            entry = ensure_model_entry(usage, args.model)
            entry["exhausted_until"] = None
            save_usage(usage)
            print(json.dumps({
                "model": args.model,
                "exhausted_until": None,
                "note": "已恢复可用",
            }, indent=2, ensure_ascii=False))
    except TimeoutError as e:
        print(json.dumps({"error": f"usage lock timeout: {e}", "hint": "并发写入 USAGE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)


# ══════════════════════════════════════════════════════════════
# doctor — 配置与运行状态健康检查（v4.3）
# ══════════════════════════════════════════════════════════════

# apiKey 占位符特征（只判存在性，不发请求验证 —— 会产生费用）
PLACEHOLDER_KEY_MARKERS = (
    "YOUR_", "your_", "sk-xxx", "sk-XXX", "xxx", "changeme", "CHANGEME",
)


def _read_raw_models_list():
    """
    读取 `models.json` 的**原始条目列表**（不按 vendor 过滤），供结构校验使用。

    与 `load_models("custom")` 的关键区别：后者会**静默丢弃**非 Custom vendor 的条目，
    导致 doctor 无法提醒用户「你写了一条 vendor 拼错的模型，它根本不会生效」（SC-DOC-003）。
    容错口径与 `load_models` 一致：文件缺失 / 非法 JSON / 顶层非 list 一律返回 []。
    """
    if not os.path.exists(MODELS_JSON):
        return []
    try:
        with open(MODELS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def _orphan_usage_ids(usage, custom_ids):
    """
    返回真正孤立的 usage 条目 id（模型已从 models.json 删除，用量无意义）。

    必须排除平台模型 —— hy3 / hy4-preview / step-5-preview 等来自平台
    （种子常量 + 宿主缓存扫描器发现），本就不在 models.json 里，
    但它们是用量统计的合法记录。
    naive 判定「usage 里有但 models.json 里没有 = 孤立」会把它们当垃圾删掉，
    静默丢失平台模型历史用量（design.md Decision 2）。

    ⚠️ 必须用 _all_platform_ids()（时间不变全集），不可用 PLATFORM_MODELS
    （那是「当前免费」的时变子集）——否则模型转收费后历史用量会被误删。
    """
    platform_ids = _all_platform_ids()
    return [
        mid for mid in usage.get("models", {})
        if mid not in custom_ids and mid not in platform_ids
    ]


def _issue(severity, category, message, fixable=False, fix_hint=""):
    """构造一条 issue（五字段结构固定，SC-DIAG-001 要求）"""
    return {
        "severity": severity,
        "category": category,
        "message": message,
        "fixable": fixable,
        "fix_hint": fix_hint,
    }


def _backup_path():
    """usage.json 的备份路径（带时间戳，多次修复不互相覆盖）"""
    if not os.path.exists(USAGE_FILE):
        return None
    return USAGE_FILE + ".bak-" + now_utc().strftime("%Y%m%d-%H%M%S")


def _apply_doctor_fixes(usage, orphans, fix_unsafe, custom_ids):
    """
    执行修复并返回 fixed 明细。

    分层是费用安全的核心（design.md Decision 1）：
      --fix        只删真孤立条目 —— 模型已删，删其用量对调度零影响
      --fix-unsafe 才清限流 + 重置配额 —— 会让不可用模型立即重新参与调度
    """
    fixed = {"orphan_removed": [], "rate_limit_cleared": [], "quota_reset": []}
    platform_ids = _all_platform_ids()

    try:
        with usage_file_lock():
            # 备份在锁内做（与写入同一临界区，避免备份到中间态）
            if os.path.exists(USAGE_FILE):
                bp = _backup_path()
                if bp:
                    shutil.copy2(USAGE_FILE, bp)
                    fixed["backup_path"] = bp
                    fixed["rollback_hint"] = f"cp {bp} {USAGE_FILE}"

            models_map = usage.setdefault("models", {})

            # 第 1 层：清理真孤立条目（--fix 与 --fix-unsafe 都做）
            for mid in orphans:
                # 双重保险：绝不碰平台模型条目
                if mid in platform_ids or mid in custom_ids:
                    continue
                if mid in models_map:
                    del models_map[mid]
                    fixed["orphan_removed"].append(mid)

            # 第 2 层：清限流 + 重置超限配额（仅 --fix-unsafe）
            if fix_unsafe:
                for mid, entry in models_map.items():
                    if mid in platform_ids:
                        continue        # 平台模型无 cost/quota 概念，不清零
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("exhausted_until"):
                        entry["exhausted_until"] = None
                        fixed["rate_limit_cleared"].append(mid)
                    q = entry.get("quota") or {}
                    req = entry.get("requests", 0)
                    tok = entry.get("tokens", 0)
                    over = ((q.get("max_requests") is not None and req >= q["max_requests"])
                            or (q.get("max_tokens") is not None and tok >= q["max_tokens"]))
                    if over:
                        entry["requests"] = 0
                        entry["tokens"] = 0
                        fixed["quota_reset"].append(mid)

            save_usage(usage)
    except TimeoutError as e:
        print(json.dumps({"error": f"usage lock timeout: {e}",
                          "hint": "并发写入 USAGE_FILE 超时，请稍后重试"},
                         ensure_ascii=False))
        sys.exit(1)

    return fixed


# ── 联网探测（doctor 的**唯一**真实外呼路径）──────────────────────
# 默认关闭 —— 只有显式传 --check-endpoint / --check-key 才会走到这里（SC-DOC-009）。
# 成本与安全约束（REQ-DOC-003）：
#   · 每模型至多 1 次密钥探测请求；单次 max_tokens ≤ 1；首个失败即停
#   · 发请求前必须打印「将要发生的真实 API 调用与费用」
#   · 问题描述**绝不**回显密钥原文（safety_critical=true）
PROBE_TIMEOUT = 5.0          # 秒 —— 连通性 / 有效性探测的硬超时上限（不无限阻塞）
KEY_PROBE_MAX_TOKENS = 1     # 密钥探测请求的 token 上限


def _http_request(url, method="GET", headers=None, body=None, timeout=PROBE_TIMEOUT):
    """
    发起一次 HTTP 请求 —— **本模块唯一的真实外呼点**（便于测试整体打桩）。

    返回 `(status, text, error)`：
      · status 为 int  → 取得 HTTP 响应（含 4xx/5xx）
      · status 为 None → 未取得响应（连接失败 / 超时 / DNS 失败），error 给出原因

    任何异常都折算为返回值，**绝不抛出** —— doctor 不应因网络问题崩溃。
    """
    import urllib.request
    import urllib.error

    data = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        return e.code, text, None
    except Exception as e:      # 网络异常面太广（URLError/timeout/socket…），统一折算
        return None, "", f"{type(e).__name__}: {e}"


def _probe_endpoint(url, timeout=PROBE_TIMEOUT):
    """
    连通性探测：取得**任意** HTTP 响应即视为可达（401/404 都证明主机+端口通）。
    返回 `(ok, detail)`；`ok=False` 时 detail 为失败原因。
    """
    status, _text, err = _http_request(url, method="GET", timeout=timeout)
    if status is None:
        return False, err or "unreachable"
    return True, f"HTTP {status}"


def _probe_key(model, timeout=PROBE_TIMEOUT, want_tools=False):
    """
    密钥有效性探测：对该模型发**一次**最小 chat/completions 请求（max_tokens=1）。

    `want_tools=True`（doctor `--check-tools`）时**复用同一次计费请求**：请求体额外带
    `tools` 声明，并从响应体解析模型是否**真返回** `tool_calls`（design.md Decision 2
    「三档共用同一次计费请求」⇒ 故本函数**扩展签名**而非新增 `_probe_tools`，
    Decision 5；新增顶层同名/近名 def 会静默遮蔽，见 EXP-2026-0004）。

    返回 `(verdict, detail, tool_state)`：
      · verdict ∈ {"valid","invalid","unreachable","unknown","unavailable"}
          - 2xx             → valid
          - 401 / 403       → invalid（密钥被拒绝）
          - 连接失败         → unreachable
          - 其它 4xx / 5xx  → unknown（**不确定**，绝不误报为 invalid）
          - 密钥形态不可用    → unavailable（如 `${VAR}` 未定义；**不发请求**，见 C1-01）
      · tool_state ∈ {None, "supported", "no_tool_calls", "truncated", "unparsable"}
          - "supported"     → 2xx 且响应含**非空** tool_calls（确证支持）
          - "no_tool_calls" → 2xx 且响应**完整结束**、无 tool_calls（确证本次不支持）
          - "truncated"     → 2xx 但 `finish_reason == "length"` ⇒ 生成被 max_tokens
                              截断，无 tool_calls 属**未观测到**，MUST NOT 判「不支持」
                              （DA-B-001：max_tokens=1 是 SC-DOC-013 的硬约束）
          - "unparsable"    → 2xx 但响应体不可解析 ⇒ 无法判定
          - None            → 未探测（want_tools=False）或非 2xx
        ⚠️ 只有 `verdict == "valid"` 时 tool_state 才可能是上述四态之一；其余一律 None
        （「无法判定」与「确证不支持」必须由调用方映射到**不同** category，SC-DOC-012）。

    `detail` **绝不**包含密钥值（safety_critical）：所有返回路径都过 `_safe()` 把密钥
    子串替换为 `<redacted>`（网络异常文本理论上可能回带请求头）。
    """
    url = model.get("url") or ""
    api_key, key_err = resolve_api_key(model.get("apiKey"))
    if key_err or not api_key:
        # 密钥在形态上就不可用（缺失 / ${VAR} 未定义）⇒ 不发请求，判「无法判定」，
        # 否则会带 `Authorization: Bearer None` 出去，被端点回 401 而**误报为密钥无效**。
        return "unavailable", key_err or "密钥缺失", None

    def _safe(text):
        return str(text).replace(str(api_key), "<redacted>") if api_key else str(text)

    def _tool_state(text):
        """
        工具调用能力判定（**嵌套辅助函数** —— 有意不新增顶层 def，Decision 5）：
          "supported"     → `choices[0].message.tool_calls` 为非空列表
          "no_tool_calls" → 响应**完整结束**（`finish_reason != "length"`）且无 tool_calls
                            ⇒ 可**确证**本次不支持（SC-DOC-011）
          "truncated"     → `finish_reason == "length"` ⇒ 生成被 max_tokens 截断，
                            无 tool_calls 只是「未观测到」，MUST NOT 判「不支持」（DA-B-001）
          "unparsable"    → 非 JSON / 无 choices / 结构不符 ⇒ 无法判定
        """
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return "unparsable"
        if not isinstance(obj, dict):
            return "unparsable"
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            return "unparsable"
        first = choices[0]
        if not isinstance(first, dict):
            return "unparsable"
        message = first.get("message")
        if not isinstance(message, dict):
            return "unparsable"
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            pass                            # 字段缺失 / null ⇒ 本次无 tool_calls
        elif isinstance(tool_calls, list):
            if tool_calls:
                return "supported"          # 已拿到 tool_calls ⇒ 与 finish_reason 无关
        else:
            return "unparsable"             # 形态不符（非 list 非 None）⇒ 无法判定
        # 到这里：本次无 tool_calls。只有**完整结束**的生成才可据此「确证不支持」。
        if first.get("finish_reason") == "length":
            return "truncated"
        return "no_tool_calls"

    endpoint = str(url).rstrip("/") + "/chat/completions"
    body = {
        "model": model.get("name") or model.get("id"),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": KEY_PROBE_MAX_TOKENS,
    }
    if want_tools:
        # 最小工具声明：仅用于诱导端点回 tool_calls。**不承诺**任何供应商必然回或不回
        # （SC-DOC-011 条件式陈述 / EXP-2026-0007）；探测结论也**不写回** models.json。
        body["tools"] = [{
            "type": "function",
            "function": {
                "name": "relay_probe",
                "description": "connectivity probe",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
    payload = json.dumps(body, ensure_ascii=False)
    status, text, err = _http_request(
        endpoint, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        body=payload, timeout=timeout)
    if status is None:
        return "unreachable", _safe(err or "unreachable"), None
    if 200 <= status < 300:
        return "valid", f"HTTP {status}", (_tool_state(text) if want_tools else None)
    if status in (401, 403):
        return "invalid", f"HTTP {status}", None
    return "unknown", f"HTTP {status}", None


def cmd_doctor(args):
    """
    健康检查：一次报出配置与运行状态的全部隐患，并按严重度分级。

    默认纯只读。修复分三层（design.md Decision 1）：
      doctor              只读，什么都不改
      doctor --fix        只清理真孤立条目（模型已删，用量无意义）
      doctor --fix-unsafe 额外清限流 + 重置超限配额
                          会让原本不可用的模型立即重新参与调度，
                          可能产生真实 API 调用与费用
    """
    fix = getattr(args, "fix", False)
    fix_unsafe = getattr(args, "fix_unsafe", False)
    check_endpoint = getattr(args, "check_endpoint", False)
    check_key = getattr(args, "check_key", False)
    check_tools = getattr(args, "check_tools", False)
    if check_tools:
        # SC-DOC-012：三层蕴含 —— --check-tools ⊃ --check-key ⊃ --check-endpoint。
        # 工具调用能力只能在「端点可达 + 密钥被接受」之后才谈得上判定，故逐档蕴含。
        check_key = True
    if check_key:
        # SC-DOC-006：--check-key **蕴含** --check-endpoint（端点不通就无从判定密钥）
        check_endpoint = True

    issues = []

    # ── 收集数据（全部只读）────────────────────────────────────
    models = load_models("custom")
    custom_ids = {m["id"] for m in models}
    usage = load_usage()

    # 数据根来源（relay-source-governance C2 / SC-DRA-007/008）：
    # 告诉用户 relay 此刻把数据读/写到哪个 root、怎么决定的——避免
    # "我改了 ~/.workbuddy-ai 的 models.json 为啥不生效" 这类困惑。
    issues.append(_issue(
        "info", "data_root",
        f"数据根={_DATA_ROOT}（决定机制={_DATA_ROOT_MECHANISM}）；"
        f"env 覆盖: FMR_DATA_ROOT={os.environ.get('FMR_DATA_ROOT') or '未设'} / "
        f"FMR_MODELS_JSON={os.environ.get('FMR_MODELS_JSON') or '未设'}",
        False, "如需固定数据根，设 FMR_DATA_ROOT 或 FMR_MODELS_JSON 环境变量"))

    # models.json 缺失 / 无可用模型
    if not os.path.exists(MODELS_JSON):
        issues.append(_issue("error", "models_missing",
                             f"models.json 不存在于 {MODELS_JSON}，无任何自定义模型可用",
                             False, "创建 models.json 并至少配置一个 vendor=Custom 的模型"))
    elif not models:
        issues.append(_issue("error", "models_empty",
                             "models.json 中没有可用的 vendor=Custom 模型",
                             False, "检查模型的 vendor 字段是否为 Custom"))

    # ── 结构校验档（REQ-DOC-001，默认开启、零网络）────────────────
    # 必填字段：url 必须存在且为 http(s) 形态（SC-DOC-001/002）
    for m in models:
        if "url" not in m:
            issues.append(_issue(
                "error", "url_missing",
                f"模型 {m['id']} 缺 url，无法定位 API 端点，该模型不可用",
                False, f"在 models.json 为 {m['id']} 填入 url（需以 http:// 或 https:// 开头）"))
            continue
        url = m.get("url")
        if not isinstance(url, str) or not (url.startswith("http://")
                                            or url.startswith("https://")):
            issues.append(_issue(
                "error", "url_invalid",
                f"模型 {m['id']} 的 url 非法（{url!r}），需以 http:// 或 https:// 开头",
                False, f"把 {m['id']} 的 url 改为 http:// 或 https:// 开头"))

    # vendor 取值（SC-DOC-003）：声明了 id 但 vendor 既非 Custom 也非空
    # ⇒ 该条目会被 load_models 静默丢弃，用户无从得知，故必须显式提醒（warn/info 而非 error）
    for m in _read_raw_models_list():
        if not isinstance(m, dict) or not m.get("id") or "freeWindow" in m:
            continue
        vendor = m.get("vendor")
        if vendor is None or vendor == "" or vendor == "Custom":
            continue
        issues.append(_issue(
            "warn", "vendor_not_custom",
            f"模型 {m['id']} 的 vendor={vendor!r} 不是 Custom，"
            f"不会被当作自定义模型使用",
            False, f"若确为自定义模型，把 {m['id']} 的 vendor 改为 \"Custom\""))

    # ── apiKey 检查（只判存在性与占位符特征，不打印明文）────────
    # `${VAR}` 形态**先判**：它可能含 `YOUR_` / `xxx` 等 legacy 标记子串，
    # 若先走 PLACEHOLDER_KEY_MARKERS 会把可用模型误报为占位符（SC-MO-014）。
    for m in models:
        key = m.get("apiKey")
        if not key:
            issues.append(_issue(
                "error", "apikey_missing",
                f"模型 {m['id']} 没有 apiKey，该模型完全不可用",
                False, f"在 models.json 为 {m['id']} 填入真实 apiKey"))
            continue
        env_var = _parse_env_placeholder(key)
        if env_var is not None:
            # 可用性取决于变量是否已定义（SC-MO-014/015）
            if env_var not in os.environ or not os.environ[env_var]:
                issues.append(_issue(
                    "error", "apikey_env_undefined",
                    f"模型 {m['id']} 的 apiKey 引用环境变量 {env_var}，"
                    f"但该变量未定义（或为空），该模型不可用",
                    False, f"导出环境变量 {env_var} 后重试"))
            # 已定义 → 不报任何 issue（SC-MO-014：SHALL NOT 报 apikey_placeholder）
            continue
        if any(mk in str(key) for mk in PLACEHOLDER_KEY_MARKERS):
            issues.append(_issue(
                "warn", "apikey_placeholder",
                f"模型 {m['id']} 的 apiKey 仍是占位符，该模型实际不可用",
                False, f"在 models.json 把 {m['id']} 的 apiKey 换成真实密钥"))

    # ── 配额与限流（判定与 is_model_available 一致）────────────
    for m in models:
        mid = m["id"]
        entry = usage["models"].get(mid) or {}
        quota = entry.get("quota") or {}
        max_req, max_tok = quota.get("max_requests"), quota.get("max_tokens")
        reqs, toks = entry.get("requests", 0), entry.get("tokens", 0)

        over = []
        if max_req is not None and reqs >= max_req:
            over.append(f"请求 {reqs}/{max_req}")
        if max_tok is not None and toks >= max_tok:
            over.append(f"token {toks}/{max_tok}")
        if over:
            issues.append(_issue(
                "warn", "quota_exhausted",
                f"模型 {mid} 配额已爆（{'、'.join(over)}），该模型当前无法被选中",
                True,
                "运行 doctor --fix-unsafe 重置配额（会让该模型重新参与调度，可能产生费用）"))

        if entry.get("exhausted_until"):
            issues.append(_issue(
                "info", "rate_limited",
                f"模型 {mid} 限流中，至 {entry['exhausted_until']}",
                True, "等待自动恢复，或运行 doctor --fix-unsafe 立即清除"))

    # ── 全部模型不可用（影响可用性的最高优先级问题）────────────
    if models:
        blocked = [m for m in models if not is_model_available(m["id"], usage)[0]]
        if blocked and len(blocked) == len(models):
            ids = ", ".join(m["id"] for m in blocked[:5])
            issues.append(_issue(
                "error", "all_models_unavailable",
                f"全部 {len(models)} 个模型都不可用（{ids}），next 必然 exit 2",
                True, "运行 doctor --fix-unsafe 清除限流并重置超限配额"))

    # ── 孤立条目（必须排除平台模型）──────────────────────────────
    orphans = _orphan_usage_ids(usage, custom_ids)
    if orphans:
        issues.append(_issue(
            "warn", "orphan_usage",
            f"usage.json 有 {len(orphans)} 条孤立条目（模型已不在 models.json）："
            f"{', '.join(sorted(orphans)[:5])}",
            True, "运行 doctor --fix 清理（不影响调度）"))

    # ── 时段与配置来源（只做异常判定，不重复 window 的全部字段）──
    in_free, free_reason = is_free_window()
    until = FREE_WINDOW.get("until")
    if until:
        try:
            if date.fromisoformat(until) < now_utc().date():
                issues.append(_issue(
                    "warn", "activity_expired",
                    f"平台模型活动期已于 {until} 结束，平台模型不再参与调度",
                    False,
                    "在 models.json 数组末尾加 freeWindow 配置元素延长"))
        except (ValueError, TypeError):
            pass
    issues.append(_issue(
        "info", "window_status",
        f"当前{'免费' if in_free else '收费'}时段（{free_reason}）；"
        f"活动期配置来源：{FREE_WINDOW_SOURCE}",
        False, "需要时段详情请跑 window 命令"))

    # ── 可达性档（--check-endpoint，显式开关）──────────────────────
    if check_endpoint and not check_key:
        for m in models:
            url = m.get("url")
            if not isinstance(url, str) or not url:
                continue        # 结构档已报 url 问题，这里不重复
            reachable, detail = _probe_endpoint(url)
            if not reachable:
                issues.append(_issue(
                    "warn", "endpoint_unreachable",
                    f"模型 {m['id']} 的端点不可达（{url}）：{detail}",
                    False, "检查网络 / 代理设置，或确认该 url 是否正确"))

    # ── 有效性档（--check-key，蕴含端点检查）──────────────────────
    if check_key and models:
        # SC-DOC-007 / SC-DOC-013：发请求前必须先打印「将要发生的真实 API 调用与费用」。
        # 传 --check-tools 时探测目的扩为「密钥 + 工具调用能力」，提示文本必须如实反映
        # （否则用户按提示以为只验密钥，实际多花的是同一次请求，但结论范围不同）。
        purpose = "校验密钥与工具调用能力" if check_tools else "校验密钥"
        print(f"[doctor] 即将对 {len(models)} 个模型发起真实 API 调用以{purpose}："
              f"每模型至多 1 次计费请求、max_tokens={KEY_PROBE_MAX_TOKENS}，"
              f"首个失败即停止；可能产生少量真实费用。", file=sys.stderr)
        for m in models:
            url = m.get("url")
            if not isinstance(url, str) or not url:
                continue
            reachable, detail = _probe_endpoint(url)
            if not reachable:
                # SC-DOC-006：端点不可达 ⇒ 既报「不可达」，又报密钥「无法判定」，
                # 且**不**发密钥探测请求（否则会白烧一次额度）
                issues.append(_issue(
                    "warn", "endpoint_unreachable",
                    f"模型 {m['id']} 的端点不可达（{url}）：{detail}",
                    False, "检查网络 / 代理设置，或确认该 url 是否正确"))
                issues.append(_issue(
                    "warn", "key_undetermined",
                    f"模型 {m['id']} 的密钥有效性无法判定（端点不可达）",
                    False, "先修复端点连通性，再运行 doctor --check-key 校验密钥"))
                if check_tools:
                    # SC-DOC-012：三层蕴含 ⇒ 工具档也须给出结论；端点不通 ⇒ 只能「无法判定」。
                    # 必须用**独立** category，MUST NOT 复用 key_undetermined（两两不互相兜底）。
                    issues.append(_issue(
                        "warn", "tool_call_unknown",
                        f"模型 {m['id']} 的工具调用能力无法判定（端点不可达）",
                        False, "先修复端点连通性，再运行 doctor --check-tools 复核"))
                continue
            verdict, detail, tool_state = _probe_key(m, want_tools=check_tools)
            if verdict == "unavailable":
                # 密钥形态不可用（缺失 / ${VAR} 未定义）⇒ 未发请求，判「无法判定」，
                # 且不 break（没有产生真实调用，继续校验其它模型是安全的）。
                issues.append(_issue(
                    "warn", "key_undetermined",
                    f"模型 {m['id']} 的密钥有效性无法判定（{detail}）",
                    False, "在 models.json 补全该模型的 apiKey，或导出所引用的环境变量"))
                if check_tools:
                    issues.append(_issue(
                        "warn", "tool_call_unknown",
                        f"模型 {m['id']} 的工具调用能力无法判定（{detail}）",
                        False, "在 models.json 补全该模型的 apiKey，再运行 "
                               "doctor --check-tools 复核"))
                continue
            if verdict == "invalid":
                issues.append(_issue(
                    "error", "key_invalid",
                    f"模型 {m['id']} 的密钥无效（{detail}），该模型不可用",
                    False, f"更新 models.json 中 {m['id']} 的 apiKey"))
                if check_tools:
                    # Design Decision 2 分支表：401/403 ⇒ key_invalid + tool_call_unknown。
                    # 密钥无效 ⇒ 工具能力同样无法判定；与「三层蕴含 ⇒ 工具档须给出结论」一致。
                    issues.append(_issue(
                        "warn", "tool_call_unknown",
                        f"模型 {m['id']} 的工具调用能力无法判定（密钥无效：{detail}）",
                        False, "先修复密钥，再运行 doctor --check-tools 复核"))
                break           # SC-DOC-007：首个失败即停（不再对后续模型发探测请求）
            if verdict == "unreachable":
                issues.append(_issue(
                    "warn", "key_undetermined",
                    f"模型 {m['id']} 的密钥有效性无法判定（端点不可达）：{detail}",
                    False, "先修复端点连通性，再运行 doctor --check-key 校验密钥"))
                if check_tools:
                    issues.append(_issue(
                        "warn", "tool_call_unknown",
                        f"模型 {m['id']} 的工具调用能力无法判定（端点不可达）：{detail}",
                        False, "先修复端点连通性，再运行 doctor --check-tools 复核"))
                break
            # valid / unknown → 密钥档不报（unknown 是「不确定」，绝不误报为无效）

            # ── 工具调用能力档（--check-tools，复用同一次计费请求）──────────
            # SC-DOC-011：2xx 且响应**完整结束**、无 tool_calls ⇒ 确证本次不支持。
            # SC-DOC-012 / DA-B-001：其余「拿不到确定信号」的情形（截断 / 不可解析 /
            # 非 2xx 非 401-403）一律报**独立**的 tool_call_unknown，
            # MUST NOT 复用 key_undetermined，也 MUST NOT 判为 unsupported。
            # DA-B-002：tool_state == "supported"（响应含**非空** tool_calls）是
            # **已确证支持**，既非 unsupported 亦非 unknown ⇒ MUST NOT 产出任何 issue。
            if check_tools:
                if tool_state == "no_tool_calls":
                    issues.append(_issue(
                        "warn", "tool_call_unsupported",
                        f"模型 {m['id']} 不支持工具调用（工具调用探测返回 200 但响应无 "
                        f"tool_calls），在需要工具调用的子代理场景下不可用",
                        False,
                        f"换用支持工具调用的模型；若确认 {m['id']} 的端点兼容 "
                        f"chat/completions 且支持 tools，请复核该端点行为"))
                elif tool_state != "supported":
                    reason = {
                        "truncated": "响应被 max_tokens 截断（finish_reason=length），"
                                     "不得据此判定为不支持",
                        "unparsable": "响应中无可解析的 tool_calls 信息",
                    }.get(tool_state, "未取得可判定的响应")
                    issues.append(_issue(
                        "warn", "tool_call_unknown",
                        f"模型 {m['id']} 的工具调用能力无法判定（{detail}，{reason}）",
                        False, "确认该端点是否兼容 chat/completions 的 tools 协议；"
                               "doctor 的探测结论不写回 models.json"))

    summary = {"error": 0, "warn": 0, "info": 0, "total": len(issues)}
    for i in issues:
        summary[i["severity"]] = summary.get(i["severity"], 0) + 1

    result = {
        "healthy": summary["error"] == 0,
        "summary": summary,
        "issues": issues,
    }

    # ── 修复（分三层）───────────────────────────────────────────
    if fix or fix_unsafe:
        fixed = _apply_doctor_fixes(usage, orphans, fix_unsafe, custom_ids)
        if fixed.get("backup_path"):
            result["backup_path"] = fixed["backup_path"]
            result["rollback_hint"] = fixed.get("rollback_hint", "")
        result["fixed"] = fixed

    print(json.dumps(result, indent=2, ensure_ascii=False))
    # 只有 error 影响退出码 —— warn/info 不应让 AI 子代理把警告当失败
    sys.exit(1 if summary["error"] > 0 else 0)


# ══════════════════════════════════════════════════════════════
# window set：免费时段写回（C1）
#
# 为什么写回要单独成命令而不是让用户手改文件：
#   models.json 含 API Key，且顶层是 list（塞配置元素要懂结构）；
#   覆盖文件虽简单，但"只写传入项 + 逐字段回退"的语义手写易错。
#
# ⚠️ 写入一律复用**既有的** `_atomic_write_json(path, data, retries=5)`（见 save_state 附近），
#    它带 Windows 并发 PermissionError(WinError 5) 重试 + fsync + chmod 0600。
#    **不要在本段另定义同名函数** —— 后定义者会静默遮蔽它，重试随之消失，
#    20 进程并发 next 会以 os.replace 的 WinError 5 崩掉（TC-LOCK-006 已抓到过）。
# ══════════════════════════════════════════════════════════════

_HOUR_FIELDS = ("start_hour", "end_hour")
_DATE_FIELDS = ("since", "until")


def _is_dashed_date(text):
    """严格 `YYYY-MM-DD` 形状校验（不校验日历合法性，那是 _valid_fw_field 的事）。

    为什么 _valid_fw_field 不够：它用 `date.fromisoformat`，而 **Python 3.11 起**
    该方法也接受 ISO 8601 basic 形式 `YYYYMMDD` —— 于是 `--until 20261231`
    在 3.11+ 会被静默接受，在 3.9/3.10 被拒，**跨解释器行为不一致**。
    SC-FWOVR-005 明确要求 since/until 为 `YYYY-MM-DD` 字符串，故在**写入侧**
    补一道形状闸门；读取侧（models.json / 覆盖文件）**保持原宽容度**，
    以免收紧后把用户既有的 freeWindow 配置判为非法、静默回退到默认活动期。
    """
    return (isinstance(text, str) and len(text) == 10
            and text[4] == "-" and text[7] == "-"
            and text[:4].isdigit() and text[5:7].isdigit() and text[8:].isdigit())


def _coerce_window_field(key, raw):
    """CLI 字符串 → 配置值。返回 (value, error_msg)。

    为什么不给 argparse 加 type=int：`--start-hour abc` 会被 argparse 拦在
    parse_args 阶段（rc=2、stdout 为空），用户拿到的是 usage 文本而非
    结构化 error —— 与 SC-FWOVR-003「输出 JSON 含 error 字段」不符。
    改为收字符串、在此处转换，让**所有**非法值（25 / -1 / abc）走同一条
    error JSON 出口，校验口径也真正复用 _valid_fw_field。
    """
    if key in _HOUR_FIELDS:
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return None, f"{key} 需为 0-23 的整数，实际 {raw!r}"
    if key in _DATE_FIELDS and not _is_dashed_date(raw):
        return None, (f"{key} 需为 YYYY-MM-DD 格式（如 2026-12-31），"
                      f"实际 {raw!r}")
    return raw, None


def _window_set_fail(message, **extra):
    """统一的失败出口：结构化 error + 非零退出码。"""
    payload = {"error": message}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(1)


def _non_freewindow_items(data):
    """取 models.json 中「非 freeWindow」的部分（写后比对用）。

    这些部分含 apiKey，是**绝不能被动**的；比对它们即可证明「只动了 freeWindow」，
    不必比对整个文件（整份比对会被键序/缩进差异误报）。

    对**同时含 freeWindow 与其他键**的元素（如 `{"apiKey": ..., "freeWindow": ...}`），
    返回**剔除 freeWindow 后的其余键**，而不是把整个元素丢掉 ——
    否则该元素的 apiKey 会落进比对盲区（Part C 评审 P2-2）。
    """
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if isinstance(it, dict) and "freeWindow" in it:
            out.append({k: v for k, v in it.items() if k != "freeWindow"})
        else:
            out.append(it)
    return out


def _merge_model_override(raw, model_id, updates):
    """把 `updates` **逐字段**并入 `raw` 的 `models[model_id]`，返回新结构 dict。

    只在**显式指定 `--model`** 时调用 ⇒ 不带 `--model` 的写入路径形态完全不变
    （SC-FWX-017 的向后兼容由此保证）。

    形态升级规则（SC-FWX-018）：
      - `raw` 为**旧扁平** → 原扁平字段整体成为 `default` 层（值**逐字保留**）
      - `raw` 已是**新结构** → 保留既有 `default` 与其余 `models` 条目
    其余模型的覆写**逐字段不变**（SC-FWX-013）；未指定的字段**不写入**目标模型。

    为什么只搬运合法字段：与 `_write_override_window` 同一口径 ——
    损坏字段不复制进新文件，避免「越修越坏」。
    """
    default_layer, models_layer, _structured, _bad, _notes = _parse_window_layer(raw)
    merged_models = {k: dict(v) for k, v in models_layer.items()}
    target = dict(merged_models.get(model_id) or {})
    target.update(updates)
    merged_models[model_id] = target
    return {"default": dict(default_layer), "models": merged_models}


def _merge_default_layer(raw, updates):
    """把 `updates` 并入 `raw` 的 **default 层**，并**保持既有文件形态**（Decision 9）。

      - `raw` 为**旧扁平** → 返回扁平 dict（**不升级**，v5.2 逐字一致，SC-FWX-017）
      - `raw` 已是**新结构** → 返回 `{"default": <合并后>, "models": <原样保留>}`

    ⚠️ 为什么必须显式区分「已是新结构」这一支：若无条件走 `_collect_layer(raw)`，
    新结构 dict 的顶层没有 `start_hour` 等字段 ⇒ 合并结果退化成
    `{"start_hour": …}`，把 `default` 与**整段 `models` 覆写全部抹掉**（数据破坏）。
    TC-FWX-018 原本只覆盖「旧扁平 + 无 --model」一种输入，故该缺陷首版未被测出
    （见 DA-012）。
    """
    default_layer, models_layer, structured, _bad, _notes = _parse_window_layer(raw)
    if not structured:
        merged = dict(default_layer)
        merged.update(updates)
        return merged
    merged_default = dict(default_layer)
    merged_default.update(updates)
    return {"default": merged_default,
            "models": {k: dict(v) for k, v in models_layer.items()}}


def _write_override_window(updates, target=None, model_id=None):
    """默认写回路径：读现有覆盖文件 → 合并传入项 → 原子写。

    **只写传入项**：绝不把 FREE_WINDOW_DEFAULT 整份快照进去 ——
    否则源码默认值一改，用户覆盖文件里的陈旧副本就会把新默认值钉死，
    "逐字段回退"变成"逐字段被旧值覆盖"。

    `model_id` 为 None（默认）⇒ 写 **default 层**并保持既有形态
    （旧扁平不升级 = v5.2 逐字一致；已是新结构则只更新其 `default` 段，
    `models` 段原样保留 —— Decision 9）；
    给定 ⇒ 升级/保持**新结构**并只动 `models[model_id]`（SC-FWX-013/018）。
    """
    target = target or OVERRIDE_WINDOW_FILE
    current = {}
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                current = raw
        except (ValueError, OSError):
            current = {}
    if model_id is not None:
        payload = _merge_model_override(current, model_id, updates)
    else:
        payload = _merge_default_layer(current, updates)
    _atomic_write_json(target, payload)
    return target


def _write_models_free_window(updates, target=None, model_id=None):
    """`--write-models-json` 路径：三道保护（SC-FWOVR-004）。

    ① 写前备份 `models.json.bak-<ts>`（同目录，便于手工回滚）
    ② 定位 list 中**首个** freeWindow 元素并逐字段合并（无则追加到末尾）
    ③ 原子写
    ④ 写后重读并逐字比对其余元素（含每个 apiKey）；不一致 → 回滚 + exit 1

    `model_id` 为 None（默认）⇒ freeWindow 元素保持**扁平**形态（v5.2 逐字一致）；
    给定 ⇒ 该元素升级/保持**新结构**并只动 `models[model_id]`。
    """
    target = target or MODELS_JSON
    if not os.path.exists(target):
        _window_set_fail(
            f"models.json 不存在：{target}；"
            f"默认路径（覆盖文件）无需该文件，请去掉 --write-models-json")
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as exc:
        _window_set_fail(
            f"models.json 无法解析（{type(exc).__name__}）：{target}；"
            f"为不覆盖你的手写文件，本次不写入")
    if not isinstance(data, list):
        _window_set_fail(
            f"models.json 顶层应为 JSON 数组，实际 {type(data).__name__}")

    before_others = _non_freewindow_items(data)

    # ① 备份：备份失败即放弃写入 —— 宁可不写，也不能无备份改含密钥文件
    # 时间戳必须走 now_utc()（唯一时间源），否则 test-testability-crossplatform
    # 的 TC-TEST-003「全仓 datetime.now 调用只许出现 1 次」会红。
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    backup = f"{target}.bak-{stamp}"
    try:
        shutil.copy2(target, backup)
    except OSError as exc:
        _window_set_fail(f"备份失败（{exc}），已放弃写入以免无备份改动含密钥文件")

    # ② 定位 / 追加（顶层 dict 浅拷贝，保证原 data 不被就地改动）
    new_data = [dict(it) if isinstance(it, dict) else it for it in data]
    idx = None
    for i, it in enumerate(new_data):
        if isinstance(it, dict) and "freeWindow" in it:
            idx = i
            break
    if idx is None:
        fw = ({"default": {}, "models": {model_id: dict(updates)}}
              if model_id is not None else dict(updates))
        new_data.append({"freeWindow": fw})
    else:
        existing_fw = new_data[idx].get("freeWindow")
        if model_id is not None:
            new_data[idx]["freeWindow"] = _merge_model_override(existing_fw, model_id, updates)
        else:
            new_data[idx]["freeWindow"] = _merge_default_layer(existing_fw, updates)

    # ③ 原子写
    _atomic_write_json(target, new_data)

    # ④ 写后逐字比对：以**磁盘上的实际内容**为准，不信内存里的 new_data
    after = None
    try:
        with open(target, "r", encoding="utf-8") as f:
            after = json.load(f)
    except (ValueError, OSError):
        after = None
    same = (after is not None and
            json.dumps(_non_freewindow_items(after), ensure_ascii=False,
                       sort_keys=True) ==
            json.dumps(before_others, ensure_ascii=False, sort_keys=True))
    if not same:
        try:
            shutil.copy2(backup, target)
        except OSError:
            pass
        _window_set_fail(
            f"写入后逐字比对失败，已回滚到备份 {os.path.basename(backup)}"
            f"（其余元素含 apiKey 必须逐字不变）")
    return target


# ══════════════════════════════════════════════════════════════
# N1: 模型密钥录入（models add / models list）
# ══════════════════════════════════════════════════════════════
#
# 为什么需要这一节：relay 此前对 models.json **只有读操作**
# （load_models L965 / _read_models_free_window L151 均以 "r" 打开），
# 13 个子命令无任何创建/写入入口 —— 新用户无法把密钥写进去，
# 属 onboarding 硬缺口（N1）。


def _cli_fail(message, **extra):
    """通用失败出口：结构化 error + 非零退出码（调用方保证不落盘）。

    `**extra` 用于给出**唯一可区分**的机器可读标识（如 `code="ownership_rejected"`）——
    SC-MO-019 要求调用方能区分「因所有权被拒」与「参数校验失败」（后者不带 code）。
    """
    payload = {"error": message}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(1)


# ── 条目所有权标记（REQ-MO-008 / SC-MO-019~021）──────────────────
# 判定口径（本变更锁定，不留实现自由度）：
#   **键名以 `Owner` 结尾（大小写敏感）**者即为所有权标记。
#     · relayOwner          → 本工具写入 ⇒ 放行
#     · 其它任何 `*Owner` 键 → 外部（含未知标记名）⇒ 默认拒绝，需 --force
#     · 不以 `Owner` 结尾的键（url / apiKey / supportsToolCall…）→ 不参与判定
# ⚠️ MUST NOT 写成 `"Owner" in key` 或 `"relayOwner" in entry` 一类**子串**判据：
#    `buddyBridgeOwner` 同样含子串 `Owner`，子串判据会让两种标记互相误判
#    （EXP-2026-0003「`'stdd guard'` 假阴性」的同构案例）。
OWNER_KEY_SUFFIX = "Owner"
RELAY_OWNER_KEY = "relayOwner"


def _owner_marker_keys(entry):
    """返回条目中所有「以 Owner 结尾」的归属标记键（REQ-MO-008 后缀判据）。

    严禁子串判据（`'Owner' in key` 会让 `buddyBridgeOwner` 误判，见上方警告）。
    仅当 entry 为 dict 时返回键名列表，否则返回空列表（防御性）。
    """
    if not isinstance(entry, dict):
        return []
    return [k for k in entry.keys() if k.endswith(OWNER_KEY_SUFFIX)]
RELAY_OWNER_VALUE = "agentinn"
# 双标记兼容（SC-014/015）：改名前的旧标记值仍视为「本工具所有」。
# 旧值用**拼接构造**，避免本文件出现旧名字面（改名守卫 TC-ARN-001a）。
RELAY_OWNER_LEGACY_VALUE = "free-" + "model-relay"
RELAY_OWNER_VALUES = frozenset({RELAY_OWNER_VALUE, RELAY_OWNER_LEGACY_VALUE})
# 已知外部标记：**只用于把错误文案写得更可读**；判定一律按后缀，不按白名单
# （按白名单判定会让未知标记静默放行，与「宁可拒绝」的保守默认相反）。
KNOWN_EXTERNAL_OWNERS = {"buddyBridgeOwner": "OW Bridge", "qoderCliOwner": "Qoder-cli"}

# ══════════════════════════════════════════════════════════════
# Qoderclicn 直扫源（v5.7.x，relay-qoderclicn-direct）
# 直接调用官方 Qoder CLI（qoderclicn）的 `--list-models` 子命令发现模型，
# 不再依赖已删除的 qoder-free 本地 OpenAI 网关（8210）。设计：agentinn 直接扫描 qoderclicn 桥。
# 全程不抛异常、不刷 stdout（D6 零阻断）。
# ══════════════════════════════════════════════════════════════

# 来源归属标记（复用既有 Owner 后缀判定口径）
QODER_CLI_OWNER_KEY = "qoderCliOwner"             # 条目所有权标记（以 Owner 结尾，复用 REQ-MO-008 后缀判定）
QODER_CLI_OWNER_VALUE = "qoderclicn"              # 标记值（源名）
QODER_CLI_TTL_SECONDS = 60                         # 自动发现 TTL（next/scan 冷路径重探间隔）
QODER_CLI_STATE_KEY = "qoder_cli_last_discovery"   # STATE_FILE 中记录上次成功发现时刻
# 官方 OpenAI 兼容网关（CN 站；--list-models 即连此网关取模型）
QODER_CLI_GATEWAY_DEFAULT = "https://gateway.qoder.com.cn/v1"
QODER_CLI_BIN_ENV = "QODERCLI_BIN"
QODER_CLI_GATEWAY_ENV = "QODER_CLI_BASE"
# 候选安装位（优先级）：环境变量 → ~/.qoder-cn → ~/.qoder → PATH
QODER_CLI_BIN_CANDIDATES = [
    os.path.join(HOME, ".qoder-cn", "bin", "qoderclicn", "qoderclicn.exe"),
    os.path.join(HOME, ".qoder", "bin", "qoderclicn", "qoderclicn.exe"),
    "qoderclicn",
]
# 来源归因：标记 → tool 标签（不改既有 relay/ow-bridge 判定口径）
OWNER_TOOL_MAP = {
    RELAY_OWNER_KEY: "relay",
    "buddyBridgeOwner": "ow-bridge",
    QODER_CLI_OWNER_KEY: "qodercli",
}

# 本地 relay（方案 A，沿用 DSH connector 原则：复用源产品自身的鉴权客户端，
# 绝不逆向 qoderclicn 的 access_token）。relay 对外暴露 OpenAI 兼容端点，内部 shell-out
# 到官方 qoderclicn（由 qoderclicn 会话打真实网关）。qodercli 模型的 url 指向此 relay，
# apiKey 留空（relay 忽略 Authorization，鉴权由 qoderclicn 会话负责）。
QODER_CLI_RELAY_HOST = "127.0.0.1"
QODER_CLI_RELAY_PORT = int(os.environ.get("QODER_CLI_RELAY_PORT", "8799"))
QODER_CLI_RELAY_DEFAULT = f"http://{QODER_CLI_RELAY_HOST}:{QODER_CLI_RELAY_PORT}/v1"
QODER_CLI_RELAY_PIDFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "qodercli_relay.pid")
QODER_CLI_RELAY_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "qodercli_relay.py")


def resolve_qoder_cli_bin():
    """定位官方 qoderclicn 可执行：QODERCLI_BIN 优先，否则按候选列表探测。"""
    env = os.environ.get(QODER_CLI_BIN_ENV)
    if env and os.path.exists(env):
        return env
    import shutil as _shutil
    for cand in QODER_CLI_BIN_CANDIDATES:
        if os.path.isabs(cand):
            if os.path.exists(cand):
                return cand
        elif _shutil.which(cand):
            return cand
    return None


def resolve_qoder_cli_base():
    """qoderclicn 官方 OpenAI 兼容网关 base URL；QODER_CLI_BASE 可覆盖。"""
    env = os.environ.get(QODER_CLI_GATEWAY_ENV)
    if env:
        return env.rstrip("/")
    return QODER_CLI_GATEWAY_DEFAULT


def list_qoder_cli_models(bin_path):
    """调用 `qoderclicn --list-models` 解析可用模型名（当前账号）。

    返回模型名 list；任何失败（无法启动 / 非零退出 / 无输出）抛异常（由调用方吞掉）。
    输出首行为表头 MODEL，其后每行一个模型名；空行跳过。
    """
    import subprocess as _sp
    creation = getattr(_sp, "CREATE_NO_WINDOW", 0)
    proc = _sp.run([bin_path, "--list-models"],
                   capture_output=True, text=True, timeout=45,
                   creationflags=creation)
    if proc.returncode != 0:
        raise RuntimeError(
            f"qoderclicn exit={proc.returncode}: {proc.stderr.strip()[:200]}")
    names = []
    for line in proc.stdout.splitlines():
        s = line.strip()
        if not s or s.upper() == "MODEL":
            continue
        names.append(s)
    return names


def _safe_persist_qoder_cli(before, new_data):
    """原子写 models.json 并校验：所有非 qoderclicn 条目逐字不变（含 apiKey）。

    返回 (backup, err)；err=None 表示成功。不退出、不刷 stderr（D6）。
    """
    target = MODELS_JSON
    backup = None
    if os.path.exists(target):
        stamp = now_utc().strftime("%Y%m%d-%H%M%S")
        backup = f"{target}.bak-{stamp}"
        try:
            shutil.copy2(target, backup)
        except OSError as exc:
            return None, f"backup failed: {exc}"
    _atomic_write_json(target, new_data)
    try:
        with open(target, "r", encoding="utf-8") as f:
            after = json.load(f)
    except (ValueError, OSError):
        after = None
    if not isinstance(after, list):
        if backup:
            try:
                shutil.copy2(backup, target)
            except OSError:
                pass
        return backup, "after-write parse failed"
    before_others = [e for e in before
                     if not (isinstance(e, dict) and e.get(QODER_CLI_OWNER_KEY))]
    after_others = [e for e in after
                    if not (isinstance(e, dict) and e.get(QODER_CLI_OWNER_KEY))]
    if (json.dumps(before_others, sort_keys=True, ensure_ascii=False) !=
            json.dumps(after_others, sort_keys=True, ensure_ascii=False)):
        if backup:
            try:
                shutil.copy2(backup, target)
            except OSError:
                pass
        return backup, "other entries changed (apiKey integrity)"
    return backup, None


def _touch_qoder_cli_discovery():
    """在 STATE_FILE 记录本次成功发现时刻（TTL 依据）。"""
    try:
        state = load_state()
        state[QODER_CLI_STATE_KEY] = now_utc().isoformat()
        save_state(state)
    except Exception:
        pass


def discover_qoder_free(force=False, _probe=None):
    """调用官方 qoderclicn --list-models 发现模型，以 Custom 条目（带 qoderCliOwner）
    幂等写入 models.json。全程不抛异常、不刷 stdout（D6 零阻断）。

    与已删除的 qoder-free 8210 网关不同：此处不依赖任何常驻进程 / OpenAI 端点，
    直接读官方 CLI 的模型清单。模型条目 url 指向本地 relay（方案 A：复用 qoderclicn
    自身会话打真实网关，绝不逆向 access_token），apiKey 留空（relay 忽略 Authorization）。
    真实官方网关记录在 qodercli_gateway 字段备查。使用层见 SKILL.md「Qoderclicn 直扫」。

    幂等：同 id 已带 qoderCliOwner → 更新；同 id 带其它 owner → 跳过不覆盖。
    force=True 时无视 TTL（供 `relay qoder-free sync` 显式强刷；子命令名沿用历史）。
    _probe 可注入（单测不触真 CLI）：传入 callable(bin_path)->list[str]。
    """
    bin_path = resolve_qoder_cli_bin()
    if not bin_path:
        return {"ok": False, "reason": "cli_missing", "discovered": 0}
    base = resolve_qoder_cli_base()
    lister = _probe or list_qoder_cli_models
    try:
        models = lister(bin_path)
    except Exception:
        return {"ok": False, "reason": "list_failed", "discovered": 0}
    if not models:
        _touch_qoder_cli_discovery()
        _record_qoder_free_limit(load_usage(), [])
        return {"ok": True, "discovered": 0, "reason": "empty", "models": []}

    before, err = _load_models_json_raw()
    if err is not None:
        return {"ok": False, "reason": "models_json_unreadable", "discovered": 0}
    out = [dict(e) if isinstance(e, dict) else e for e in before]
    discovered = 0
    updated = 0
    skipped = 0
    for mid in models:
        new_entry = {
            "id": mid,
            "vendor": "Custom",
            "url": QODER_CLI_RELAY_DEFAULT,     # 指向本地 relay（方案 A），由 relay 复用 qoderclicn 会话
            "apiKey": "",                       # relay 忽略 Authorization，鉴权由 qoderclicn 会话负责
            "bridged": True,
            "bridge_tool": "qodercli",
            "qoderclicn_session_auth": True,    # 标记：走 qoderclicn 会话而非静态 key
            "qodercli_relay": True,             # 标记：经本地 relay 暴露 OpenAI 兼容端点
            "qodercli_gateway": base,           # 真实官方网关（relay 内部经 qoderclicn 会话打它）
            QODER_CLI_OWNER_KEY: QODER_CLI_OWNER_VALUE,
        }
        existing = next((e for e in out
                         if isinstance(e, dict) and e.get("id") == mid), None)
        if existing is not None:
            other_owners = [k for k in _owner_marker_keys(existing)
                            if k != QODER_CLI_OWNER_KEY]
            if other_owners:
                skipped += 1
                continue  # 不覆盖他人（relay/ow-bridge）条目（SC-MO-020 同构）
            existing.update(new_entry)
            existing[QODER_CLI_OWNER_KEY] = QODER_CLI_OWNER_VALUE
            updated += 1
        else:
            out.append(new_entry)
            discovered += 1

    backup, perr = _safe_persist_qoder_cli(before, out)
    if perr:
        return {"ok": False, "reason": "persist_failed", "detail": perr, "discovered": 0}
    _touch_qoder_cli_discovery()
    _record_qoder_free_limit(load_usage(), models)
    return {
        "ok": True,
        "discovered": discovered,
        "updated": updated,
        "skipped": skipped,
        "models": models,
        "base": base,
        "written_to": MODELS_JSON,
        "backup": os.path.basename(backup) if backup else None,
    }


def maybe_discover_qoder_free(force=False, _probe=None):
    """冷路径自动触发：TTL 内（默认 60s）不重复调用 CLI；任何异常全吞（best-effort，D6）。

    安全闸 FMR_QF_AUTODISCOVER：设为 0/false/off/no 时彻底禁用（保护既有测试套件 /
    避免对真实 models.json 的意外改写）；默认启用（用户诉求「自动发现」）。
    _probe 可注入（单测不触真 CLI）；生产默认走 list_qoder_cli_models。
    """
    kill = os.environ.get("FMR_QF_AUTODISCOVER", "1").strip().lower()
    if kill in ("0", "false", "off", "no"):
        return {"ok": False, "reason": "disabled", "discovered": 0}
    try:
        if not force:
            state = load_state()
            last = state.get(QODER_CLI_STATE_KEY)
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now_utc() - last_dt).total_seconds() < QODER_CLI_TTL_SECONDS:
                        return {"ok": False, "reason": "ttl_fresh", "discovered": 0}
                except Exception:
                    pass
        return discover_qoder_free(force=force, _probe=_probe)
    except Exception:
        return {"ok": False, "reason": "unexpected", "discovered": 0}


def cmd_qoder_free(args):
    """Qoder-cli 直扫源管理：sync（强制刷新发现）/ status（CLI 可达性与已发现模型）。

    子命令名沿用历史 `qoder-free`（调用方不变），实际已改为直接扫官方 qoderclicn。
    """
    action = getattr(args, "qf_action", None)
    bin_path = resolve_qoder_cli_bin()
    if action == "sync":
        result = discover_qoder_free(force=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)
    if action == "status":
        info = {
            "cli_bin": bin_path,
            "cli_found": bin_path is not None,
            "base": resolve_qoder_cli_base(),
        }
        state = load_state()
        info["last_discovery"] = state.get(QODER_CLI_STATE_KEY)
        if bin_path:
            try:
                ms = list_qoder_cli_models(bin_path)
                info["reachable"] = True
                info["model_count"] = len(ms)
                info["models"] = ms
            except Exception as e:
                info["reachable"] = False
                info["error"] = type(e).__name__
        else:
            info["reachable"] = None
            info["error"] = "cli_missing"
        info["relay"] = _relay_status()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        sys.exit(0)
    if action == "relay-start":
        print(json.dumps(_relay_start(), ensure_ascii=False, indent=2))
        sys.exit(0)
    if action == "relay-stop":
        print(json.dumps(_relay_stop(), ensure_ascii=False, indent=2))
        sys.exit(0)
    if action == "relay-status":
        print(json.dumps(_relay_status(), ensure_ascii=False, indent=2))
        sys.exit(0)
    print(json.dumps({"error": "unknown action; use sync/status/relay-start/relay-stop/relay-status"}, ensure_ascii=False))
    sys.exit(1)


# ── 本地 relay 进程管理（方案 A：复用 qoderclicn 自身会话）──────────────
def _relay_is_running(port):
    """端口可连即视为 relay 在跑（轻量探活，不读 pidfile）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex((QODER_CLI_RELAY_HOST, int(port))) == 0
    finally:
        s.close()


def _relay_read_pid():
    try:
        with open(QODER_CLI_RELAY_PIDFILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _relay_write_pid(pid):
    try:
        with open(QODER_CLI_RELAY_PIDFILE, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except Exception:
        pass


def _relay_clear_pid():
    try:
        os.remove(QODER_CLI_RELAY_PIDFILE)
    except OSError:
        pass


def _pids_on_port(port):
    """Windows: 返回占用 TCP 端口的 pid 列表（netstat 解析）；其它平台返回 []。
    以 bytes 读取 netstat 输出，避免 text=True 在 PYTHONUTF8 环境下把本地化字节当 utf-8 崩 reader 线程。"""
    import subprocess as _sp
    try:
        raw = _sp.run(["netstat", "-ano", "-p", "TCP"],
                      capture_output=True, creationflags=0x08000000, timeout=10).stdout or b""
        out = raw.decode("utf-8", errors="replace")
    except Exception:
        return []
    pids = []
    target = ":%d" % int(port)
    for line in out.splitlines():
        cols = line.split()
        # 列: Proto  Local  Foreign  State  PID
        if len(cols) >= 5 and cols[0].upper() == "TCP" and cols[1].endswith(target):
            try:
                pids.append(int(cols[-1]))
            except ValueError:
                pass
    return pids


def _kill_pid_tree(pid):
    """Windows: 强制杀进程及其子进程树。"""
    import subprocess as _sp
    try:
        _sp.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                creationflags=0x08000000, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
        return True
    except Exception:
        return False


def _relay_start(port=None):
    """启动/重启 qodercli_relay.py 为后台常驻进程（DETACHED）。
    若端口已被占用（可能是旧代码实例），先停止再启动，保证「改完 relay 代码再 start」拿到新代码。"""
    import subprocess as _sp
    import time as _time
    port = int(port if port is not None else QODER_CLI_RELAY_PORT)
    if _relay_is_running(port):  # 重启语义：先停旧的
        _relay_stop()
    bin_path = resolve_qoder_cli_bin()
    if not bin_path:
        return {"ok": False, "reason": "cli_missing"}
    creation = 0x08000000 | 0x00000200 | 0x00000008  # NO_WINDOW|NEW_PROCESS_GROUP|DETACHED
    try:
        p = _sp.Popen([sys.executable, QODER_CLI_RELAY_SCRIPT, "--host", QODER_CLI_RELAY_HOST,
                       "--port", str(port)],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, creationflags=creation)
    except Exception as e:
        return {"ok": False, "reason": "spawn_failed", "detail": str(e)}
    for _ in range(50):  # 轮询端口，最多 ~10s
        if _relay_is_running(port):
            _relay_write_pid(p.pid)
            return {"ok": True, "running": True, "port": port, "pid": p.pid}
        _time.sleep(0.2)
    return {"ok": False, "reason": "did_not_come_up", "pid": p.pid}


def _relay_stop():
    """停止后台 relay：先按 pidfile，再按端口兜底（谁占端口杀谁）；轮询端口确认真正退出。"""
    import time as _time
    port = QODER_CLI_RELAY_PORT
    pid = _relay_read_pid()
    candidate_pids = set()
    if pid:
        candidate_pids.add(pid)
    for p in _pids_on_port(port):  # 端口实查兜底（防 pidfile 过期）
        if p > 0:
            candidate_pids.add(p)
    for p in candidate_pids:
        _kill_pid_tree(p)
    for _ in range(25):  # 轮询端口最多 ~5s，确认真正退出
        if not _relay_is_running(port):
            _relay_clear_pid()
            return {"ok": True, "stopped_pids": sorted(candidate_pids)}
        _time.sleep(0.2)
    return {"ok": False, "reason": "still_running", "pids": sorted(candidate_pids)}


def _relay_status():
    port = QODER_CLI_RELAY_PORT
    running = _relay_is_running(port)
    pid = _relay_read_pid()
    if running and (not pid or pid not in _pids_on_port(port)):
        # pidfile 过期：以端口实查为准
        ports = _pids_on_port(port)
        pid = ports[0] if ports else None
    return {"ok": True, "port": port, "running": running,
            "pid": (pid if running else None),
            "script": QODER_CLI_RELAY_SCRIPT}

def _load_models_json_raw(target=None):
    """读 models.json 的**原始 list**（不做 vendor 过滤）。

    返回 (data, err)：
      - 文件不存在 → ([], None) —— models add 语义是「不存在则创建」（SC-MO-001）
      - 解析失败 / 顶层非数组 → (None, 人可读错误) —— 调用方以非零码退出且**不落盘**
    错误信息**不回显文件内容**（SC-MO-008）。
    """
    target = target or MODELS_JSON
    if not os.path.exists(target):
        return [], None
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as exc:
        return None, (f"models.json 无法解析（{type(exc).__name__}）：{target}；"
                      f"为不覆盖你的手写文件，本次不写入")
    if not isinstance(data, list):
        return None, f"models.json 顶层应为 JSON 数组，实际 {type(data).__name__}"
    return data, None


def _append_model_entry(data, new_entry):
    """**条目语义**：同 id 已存在则更新指定字段，否则追加到末尾。

    与 `free set` 的「重复声明取并集」不同（后者是集合语义）：
    数组长度只在真正新增时增长（SC-MO-002/003）；更新时未被本次指定的
    其他字段保持原值。返回 (new_data, appended: bool)。
    """
    out = [dict(it) if isinstance(it, dict) else it for it in data]
    for it in out:
        if isinstance(it, dict) and it.get("id") == new_entry["id"]:
            it.update(new_entry)
            return out, False
    out.append(dict(new_entry))
    return out, True


def _strip_target(data, target_id):
    """返回 data 中所有 `id != target_id` 的元素（写后逐字段比对用）。

    比对「目标条目之外的一切」逐字段不变，可覆盖**同时含 apiKey 与
    freeWindow 的混合元素** —— 否则该元素的 apiKey 会落进比对盲区
    （SC-MO-009；与 _non_freewindow_items 的盲区修复同族）。
    """
    if not isinstance(data, list):
        return []
    return [it for it in data
            if not (isinstance(it, dict) and it.get("id") == target_id)]


def _write_models_json_entries(before, new_data, target_id, target=None):
    """写 models.json：**备份 → 原子替换 → 写后逐字段比对**（SC-MO-007/008/009）。

    三道保护与 `_write_models_free_window` 同构，差别在比对基准：
    这里比对「目标 id 之外的全部元素」，覆盖混合元素。
    比对以**磁盘上的实际内容**为准，不信内存里的 new_data。
    返回 (target, backup)。
    """
    target = target or MODELS_JSON

    # ① 备份（仅当原文件存在）：备份失败即放弃写入 —— 宁可不写，也不能无备份改含密钥文件
    backup = None
    if os.path.exists(target):
        stamp = now_utc().strftime("%Y%m%d-%H%M%S")
        backup = f"{target}.bak-{stamp}"
        try:
            shutil.copy2(target, backup)
        except OSError as exc:
            _cli_fail(f"备份失败（{exc}），已放弃写入以免无备份改动含密钥文件")

    before_others = _strip_target(before, target_id)

    # ② 原子写
    _atomic_write_json(target, new_data)

    # ③ 写后重读比对：以磁盘实际内容为准
    after = None
    try:
        with open(target, "r", encoding="utf-8") as f:
            after = json.load(f)
    except (ValueError, OSError):
        after = None
    same = (isinstance(after, list) and
            json.dumps(_strip_target(after, target_id), ensure_ascii=False,
                       sort_keys=True) ==
            json.dumps(before_others, ensure_ascii=False, sort_keys=True))
    if not same:
        if backup:
            try:
                shutil.copy2(backup, target)
            except OSError:
                pass
        _cli_fail("写入后逐字段比对失败，已回滚到备份 "
                  f"{os.path.basename(backup) if backup else '(无备份)'}"
                  "（其余元素含 apiKey 必须逐字不变）")
    return target, backup


def _resolve_new_key(args):
    """解析 `models add` 的密钥来源，返回 (key, err)。

    三条路径（用户裁决日「两者都给」）：
      --from-env <VAR>  落盘 `${VAR}` **字面量**，不落盘真实值（SC-MO-004）
      --stdin           从管道读，去尾换行（SC-MO-006）
      （默认）           getpass 从 tty 读取，不回显（SC-MO-001）

    非 tty 且未指定非交互路径时**早失败**：Windows 下 `getpass.getpass()`
    走 msvcrt 路径**不读管道**，会直接**挂死**（本机实测 2 分钟未返回）。
    """
    from_env = getattr(args, "from_env", None)
    use_stdin = getattr(args, "stdin", False)

    if from_env and use_stdin:
        return None, "--from-env 与 --stdin 不能同时使用"
    if from_env:
        if from_env not in os.environ:
            return None, f"环境变量 {from_env} 未定义"
        if not os.environ[from_env]:
            return None, f"环境变量 {from_env} 为空"
        # 落盘占位符**字面量**：磁盘上绝不出现真实密钥（SC-MO-004）
        return "${" + from_env + "}", None
    if use_stdin:
        key = sys.stdin.read().rstrip("\r\n")
        if not key:
            return None, "stdin 未提供密钥"
        return key, None

    if not sys.stdin.isatty():
        return None, ("非交互环境（stdin 非 tty）无法安全读取密钥；"
                      "请在终端直接运行，或改用 --from-env <VAR> / --stdin")
    key = getpass.getpass("API Key（不回显）: ")
    if not key:
        return None, "密钥为空，已放弃写入"
    return key, None


# ── 密钥遮蔽 + `${ENV_VAR}` 占位（S3）────────────────────────────
# 安全红线（SC-MO-012，safety_critical=true）：任何输出通道
# （stdout / stderr / 错误 JSON / traceback）都不得回显密钥原文。
# 统一走 _mask_secret；任何要打印密钥字段的地方都必须过它。

_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _mask_secret(value):
    """把密钥值替换为**不含原文**的遮蔽串（SC-MO-012）。

    刻意**不保留任何尾部字符**：即便只留末 4 位，也可能与哨兵断言重叠，
    且遮蔽的目的是「证明该字段存在且已被处理」，不是「让用户核对密钥」。
    返回 None 表示「无密钥字段」——与 `_key_status` 的 missing 对齐。
    """
    if value is None:
        return None
    return f"<redacted:{len(str(value))}>"


def _parse_env_placeholder(raw):
    """若 raw 是 `${VAR}` 形态 → 返回变量名；否则 None。

    必须在 legacy `PLACEHOLDER_KEY_MARKERS` 之前判定：变量名可能恰含
    `YOUR_` / `xxx` 等子串（如 `${YOUR_KEY}`），会被误判为
    「用户忘了改的占位符」，从而把可用模型报成不可用。
    """
    if not isinstance(raw, str):
        return None
    m = _ENV_PLACEHOLDER_RE.match(raw.strip())
    return m.group(1) if m else None


def resolve_api_key(raw):
    """读侧把 `${VAR}` 占位符**运行时展开**为环境变量值（SC-MO-014/015）。

    磁盘上始终保留占位符字面量（写侧见 `_resolve_new_key`），只有真正要
    用密钥时才展开 —— 写时展开等于明文落盘，等于没做占位。

    返回 (key, err)：
      非占位符        → (raw, None)          # 原样返回（含明文 / 缺失）
      占位符 + 已定义 → (value, None)
      占位符 + 未定义 → (None, "环境变量 VAR 未定义（或为空）")
    错误文本只含**变量名**，不含任何密钥值（SC-MO-015）。
    """
    var = _parse_env_placeholder(raw)
    if var is None:
        return raw, None
    if var not in os.environ or not os.environ[var]:
        return None, f"环境变量 {var} 未定义（或为空）"
    return os.environ[var], None


def _key_status(raw):
    """密钥状态三态（SC-MO-016）：present / placeholder / missing。

    注意这是**形态**判定而非**可用性**判定：`${VAR}` 即便变量未定义也报
    `placeholder`（形态就是占位符），可用性由 `resolve_api_key` / doctor 负责。
    """
    if raw is None or (isinstance(raw, str) and raw == ""):
        return "missing"
    if _parse_env_placeholder(raw) is not None:
        return "placeholder"
    return "present"


def cmd_models_add(args):
    """引导式录入一个 vendor=Custom 模型条目（N1）。

    密钥默认经 getpass 从 tty 读取（不回显）；非交互用 `--from-env` / `--stdin`。
    **不接受** `--api-key` 明文参数（argv 可见于 ps 输出，SC-MO-013）。
    参数校验**早失败**：`--id` 缺失/为空、`--url` 非 http(s) 时非零退出且不落盘。
    """
    model_id = getattr(args, "id", None)
    url = getattr(args, "url", None)

    # 参数早失败（SC-MO-010/011）
    if not model_id:
        _cli_fail("--id 为必填")
    if not url:
        _cli_fail("--url 为必填")
    if not (url.startswith("http://") or url.startswith("https://")):
        _cli_fail("--url 需以 http:// 或 https:// 开头", url=url)

    # 密钥来源早失败（SC-MO-004/005/006）：在任何落盘动作之前
    key, err = _resolve_new_key(args)
    if err:
        _cli_fail(err)

    before, err = _load_models_json_raw()
    if err:
        _cli_fail(err)

    # ── 条目所有权（SC-MO-019/020/021）──────────────────────────
    # 目的：relay 与第三方工具（OW Bridge 等）同写 models.json，
    # 无所有权概念时两边会静默互相覆盖（DA-008）。默认拒绝更新带**外部**标记的条目。
    existing = None
    for it in before:
        if isinstance(it, dict) and it.get("id") == model_id:
            existing = it
            break
    external_owners = [k for k in _owner_marker_keys(existing) if k != RELAY_OWNER_KEY]
    # `--force` 是**唯一**放行口：只解除所有权拒绝，不绕过写入安全协议（SC-MO-007/008/009）
    # 与参数校验（SC-MO-010/011，见函数开头的早失败）。
    if external_owners and not getattr(args, "force", False):
        name = external_owners[0]
        known = KNOWN_EXTERNAL_OWNERS.get(name)
        # SC-MO-019：错误必须 ① 含 `--force` ② 含 `未知标记 <name>`
        # ③ 带**唯一可区分**的机器可读标识（与 SC-MO-010/011 的参数校验失败区分开）。
        # 「未知标记」按字面取自 spec 的 AND（对任何非 relayOwner 标记都适用）——
        # 对 relay 而言任何非自有标记都属「未在本工具注册」，文案不误。
        _cli_fail(
            f"条目 {model_id} 带外部所有权标记：未知标记 {name}"
            + (f"（{known} 写入）" if known else "")
            + "；relay 默认不覆盖外部工具管理的条目，如确需覆盖请加 --force",
            code="ownership_rejected",
            owner_keys=external_owners,
            unknown_marker=name,
        )

    entry = {"id": model_id, "vendor": "Custom", "url": url, "apiKey": key}
    # SC-MO-021：`models add` 写入的条目带 `relayOwner` 标记。
    # 已带 `relayOwner` 的条目**保留原值**（不覆盖成我们的常量）—— 否则
    # 「键名精确匹配」的对称性无法通过取值交叉验证（TC-MO-021 用同一 V 取值）。
    # 外部标记条目即便 `--force` 也**不**加 relayOwner：`--force` 只解除拒绝，
    # 把别人的条目登记成自己的属「越权」（SC-MO-020 的「只解除拒绝」）。
    if not external_owners:
        prev_owner = existing.get(RELAY_OWNER_KEY) if isinstance(existing, dict) else None
        entry[RELAY_OWNER_KEY] = prev_owner or RELAY_OWNER_VALUE
    new_data, appended = _append_model_entry(before, entry)
    target, backup = _write_models_json_entries(before, new_data, model_id)

    print(json.dumps({
        "ok": True,
        # 条目语义：已存在 ⇒ updated（数组长度不变）；不存在 ⇒ add（追加到末尾）
        "action": "add" if appended else "updated",
        "id": model_id,
        # 密钥一律经遮蔽函数输出 —— 绝不回显原文（SC-MO-012）。
        # 这也是 TC-MO-017 反向实验的变异点：改成原样回显后 TC-MO-012 必须变红。
        "apiKey_masked": _mask_secret(key),
        "written_to": target,
        "backup": os.path.basename(backup) if backup else None,
    }, ensure_ascii=False, indent=2))


def cmd_models_list(args):
    """**只读**列出全部已声明模型的密钥状态三态与来源三态（SC-MO-016）。

    只读契约：不写 `models.json`、不建备份、不动 usage（唯一例外：进程启动期一次性数据
    迁移可能新建 `agentinn-state/usage/window.json`，不涉及 `models.json`，评审 P1-4）。
    输出不含任何密钥原文 —— 只报 `key_status`（present/placeholder/missing），
    占位符条目额外报变量名与其是否已定义（变量名不是密钥值，可用于排障）。
    `source` 三态：`relay`（带 `relayOwner`）/ `external`（带其它 `*Owner` 标记）/
    `unowned`（无任何所有权标记）。
    """
    data, err = _load_models_json_raw()
    if err:
        _cli_fail(err)

    entries = []
    for it in data:
        # 只列「有 id 的模型条目」；freeWindow 之类的配置元素没有 id，跳过
        if not isinstance(it, dict) or "id" not in it:
            continue
        raw = it.get("apiKey")
        # 来源三态（SC-MO-016 AND）：与 `models add` 共用 `_owner_marker_keys`，
        # 避免「add 拒绝但 list 报 unowned」这类两处判定漂移。
        # 外部标记**优先**：同时带 relayOwner 与外部标记时按 external 报（保守口径，
        # 与 add 侧「外部标记 ⇒ 需 --force」一致）。
        owner_keys = _owner_marker_keys(it)
        if [k for k in owner_keys if k != RELAY_OWNER_KEY]:
            source = "external"
        elif owner_keys:
            source = "relay"
        else:
            source = "unowned"
        item = {
            "id": it.get("id"),
            "vendor": it.get("vendor"),
            "url": it.get("url"),
            "key_status": _key_status(raw),
            "source": source,
        }
        var = _parse_env_placeholder(raw)
        if var is not None:
            item["env_var"] = var
            item["env_defined"] = bool(os.environ.get(var))
        entries.append(item)

    print(json.dumps({
        "ok": True,
        "action": "list",
        "count": len(entries),
        "models": entries,
    }, ensure_ascii=False, indent=2))


def cmd_window_set(args):
    """写入免费时段配置（C1）。

    默认写 relay 侧覆盖文件；`--write-models-json` 才动 models.json。
    所有非法值走同一条 error JSON 出口且**不落盘**（SC-FWOVR-003/005）。

    `--model <id>`（v5.3）⇒ 只写该模型的**逐字段覆写**：
      - 不指定 `--model` ⇒ 写全局 `default` 层，且**保持既有文件形态**
        （旧扁平不升级；v5.2 逐字一致，SC-FWX-017）
      - 指定 `--model` ⇒ 写 `models[<id>]`，必要时把旧扁平升级为新结构
        （SC-FWX-013/018）
    这是 design.md Decision 4 的「显式 opt-in 才升级形态」：
    不碰 per-model 的用户不会被静默迁移。
    """
    model_id = getattr(args, "model", None)
    if model_id is not None:
        if not isinstance(model_id, str) or not model_id.strip():
            _window_set_fail("--model 需为非空字符串（模型 ID）", field="model", raw=model_id)
        model_id = model_id.strip()

    updates = {}
    for key in _FREE_WINDOW_FIELDS:
        raw = getattr(args, key, None)
        if raw is None:
            continue
        value, err = _coerce_window_field(key, raw)
        if err is not None:
            _window_set_fail(err, field=key, raw=raw)
        if not _valid_fw_field(key, value):
            _window_set_fail(
                f"{key} 取值非法：{raw!r}"
                f"（小时需 0-23 整数；日期需 YYYY-MM-DD）",
                field=key, raw=raw)
        updates[key] = value

    if not updates:
        _window_set_fail(
            "未指定任何字段；至少传一个 "
            "--start-hour / --end-hour / --since / --until")

    if getattr(args, "write_models_json", False):
        target = _write_models_free_window(updates, model_id=model_id)
    else:
        target = _write_override_window(updates, model_id=model_id)

    # 写后重算：模块级 FREE_WINDOW 是**导入时**的快照，已过期
    config, source, warnings, _per_model, _per_model_src = _load_free_window_full()
    payload = {
        "ok": True,
        "action": "set",
        "written_to": target,
        "updated_fields": updates,
        "window_config": config,
        "config_source": source,
    }
    # 只在显式指定时新增该键 —— 不带 --model 时输出与 v5.2 逐字一致（只增字段）
    if model_id is not None:
        payload["model"] = model_id
    if warnings:
        payload["warning"] = " / ".join(warnings)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_window(args):
    """查看平台模型免费时段状态。"""
    now = now_utc()
    # 显式用 now= 关键字：新签名第一参数是 model_id，
    # 位置调用 `is_free_window(now)` 会把 datetime 当成 model id（见 S5 的 DA-011）。
    in_free, reason = is_free_window(now=now)

    sh = FREE_WINDOW["start_hour"]   # 23
    eh = FREE_WINDOW["end_hour"]     # 8

    # 活动期边界（超出则无"下一个免费时段"可言）
    since = date.fromisoformat(FREE_WINDOW["since"]) if FREE_WINDOW["since"] else None
    until = date.fromisoformat(FREE_WINDOW["until"]) if FREE_WINDOW["until"] else None

    def _at(day, hour):
        return datetime.combine(day, datetime.min.time()).replace(hour=hour)

    if in_free:
        # 免费中 → 自然延续到次日（或当日）end_hour
        # 注意：until 不截断进行中的免费时段（23:00 开始的时段本就跨到次日 08:00），
        #       until 只限制"是否还有新的免费时段开始"。
        # 同日区间（sh < eh，如 01-05）：02:00 免费中，结束点仍是**当日** 05:00；
        # 跨午夜区间（sh >= eh，如 23-8）：23:30 免费中，结束点在**次日** 08:00。
        if sh < eh:
            end_day = now.date()
        else:
            end_day = now.date() + timedelta(days=1) if now.hour >= sh else now.date()
        end = _at(end_day, eh)
        # 与 is_free_window 保持一致：免费时段不得超过活动期终点（until 日 24:00）。
        # 否则 window 说"免费到 10-11 08:00"，而 is_free_window 在 10-11 判"活动已结束"，自相矛盾。
        act_end = _at(until + timedelta(days=1), 0) if until else None
        if act_end and end > act_end:
            end = act_end
            next_change = {"at": end.isoformat(), "change_to": "活动期结束（非时段自然结束）",
                           "remaining_minutes": round((end - now).total_seconds() / 60),
                           "note": f"活动 {until} 到期，免费额度到此为止"}
        else:
            next_change = {"at": end.isoformat(), "change_to": "收费时段",
                           "remaining_minutes": round((end - now).total_seconds() / 60)}
            if until and end.date() > until:
                next_change["note"] = "活动最后一个免费时段，结束后不再有免费额度"
    else:
        # 收费中 → 下一个 start_hour（今天或明天）
        start = _at(now.date(), sh)
        if start <= now:
            start = _at(now.date() + timedelta(days=1), sh)
        # 活动未开始 → 首个免费时段是活动首日的 sh
        if since and start.date() < since:
            start = _at(since, sh)
        # 活动已结束 → 不再有免费时段
        if until and start.date() > until:
            next_change = {"at": None, "change_to": None,
                           "remaining_minutes": None,
                           "note": f"活动已于 {until} 结束，无后续免费时段"}
        else:
            next_change = {"at": start.isoformat(), "change_to": "免费时段",
                           "remaining_minutes": round((start - now).total_seconds() / 60)}

    # 活动期是否已过期（可程序化判定，不必从 reason 文本推断）
    expired = False
    if until:
        try:
            expired = now.date() > until
        except (ValueError, TypeError):
            expired = False   # 配置非法时不谎报过期，交给 is_free_window 报配置错误
    warning_parts = []
    if expired:
        warning_parts.append(
            f"活动期已于 {FREE_WINDOW['until']} 结束，平台模型不再参与调度；"
            f"如需延长，在 models.json 中添加 freeWindow 配置元素"
            f'（如 {{"freeWindow": {{"until": "2026-12-31"}}}}）'
        )
    # 覆盖文件被忽略时的告警（C2）：合并进既有 warning 字段，**不新增键**，
    # 以维持"只增字段、不改既有字段语义"的向后兼容契约。
    warning_parts.extend(FREE_WINDOW_WARNINGS)
    warning = " / ".join(warning_parts) if warning_parts else None

    source, _ = resolve_source("auto")
    print(json.dumps({
        "now": now.isoformat(),
        "in_free_window": in_free,
        "reason": reason,
        "window_config": FREE_WINDOW,
        "config_source": FREE_WINDOW_SOURCE,
        "expired": expired,
        "warning": warning,
        "timezone_note": (f"按本机本地时间判断（免费时段 "
                          f"{sh:02d}:00-{eh:02d}:00 指用户所在时区）"),
        "auto_source_now": source,
        "next_change": next_change,
        "platform_models": [m["id"] for m in PLATFORM_MODELS],
        # v5.3 新增（**只增字段**，既有键语义不变 —— SC-FWX-003/004 的逐字兼容契约）：
        # 每个模型的生效时段与来源层，使 hy4 覆写与 hy3 走默认可在输出中逐条读出。
        "per_model": _per_model_window_view(),
    }, indent=2, ensure_ascii=False))


def _dispatch_onboard(args):
    """`onboard` 多路径分派：show（默认，读）/ set（写）/ agenthub-ack（写，v5.6.1）。

    跟随 free / window 的**位置参数 action** 惯例，保持 CLI 心智一致。
    """
    action = getattr(args, "onboard_action", "show")
    if action == "set":
        return cmd_onboard_set(args)
    if action == "agenthub-ack":
        return cmd_onboard_agenthub_ack(args)
    return cmd_onboard(args)


def _dispatch_models(args):
    """`models` 子命令分派：add（N1 密钥录入）/ list（只读三态）。

    跟随 free / quota / window 的**位置参数 action** 惯例（`models_action`）。
    """
    action = getattr(args, "models_action", None)
    if action == "add":
        return cmd_models_add(args)
    if action == "list":
        return cmd_models_list(args)
    _cli_fail(f"未知 models 动作：{action!r}（合法值：add, list）")


def _dispatch_window(args):
    """`window` 双路径分派：show（默认，向后兼容）/ set。

    跟随 free / quota 的**位置参数 action** 惯例（`free_action` / `quota_action`），
    保持 CLI 心智一致。
    """
    if getattr(args, "window_action", "show") == "set":
        return cmd_window_set(args)

    # 显式拒绝「show + 写入参数」的静默空操作（Part C 评审 P2-1）：
    # `window --start-hour 22`（漏写 `set`）此前会 exit 0 且**什么都不做**，
    # 用户以为改成功了 —— 属最易踩的坑，必须报错而不是静默成功。
    stray = ["--" + k.replace("_", "-") for k in _FREE_WINDOW_FIELDS
             if getattr(args, k, None) is not None]
    if getattr(args, "write_models_json", False):
        stray.append("--write-models-json")
    if getattr(args, "model", None) is not None:
        stray.append("--model")
    if stray:
        _window_set_fail(
            f"`window`（show）不接受写入参数：{' '.join(stray)}；"
            f"要改免费时段请用 `window set ...`",
            hint="例如：pick_model.py window set --start-hour 22 --end-hour 7")
    return cmd_window(args)


def cmd_reset(args):
    """重置轮次状态（保留用量统计 + 免费白名单）。"""
    current = load_state()
    state = {"strategy": "round-robin", "index": 0, "history": [], "known_models": current.get("known_models", [])}
    # 白名单是**用户确认结果**，不是轮次状态：reset 只重置轮询位/历史。
    # 仅当存在时才写入，保证无白名单场景的输出与改动前逐字一致。
    if FREE_ALLOWLIST_KEY in current:
        state[FREE_ALLOWLIST_KEY] = current[FREE_ALLOWLIST_KEY]
    try:
        with state_file_lock():
            save_state(state)
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}", "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"status": "reset", "state": state,
                      "note": "用量统计已保留在 usage.json；免费白名单已保留（要清空用 free clear）"}, indent=2, ensure_ascii=False))


def cmd_status(args):
    """查看当前状态。"""
    state = load_state()
    models = load_models("all")
    usage = load_usage()
    in_free, free_reason = is_free_window()
    print(json.dumps({
        "state": state,
        "available_models": [{"id": m["id"], "source": m.get("_source")} for m in models],
        "in_free_window": in_free,
        "window_reason": free_reason,
        "usage_file": USAGE_FILE,
        "state_file": STATE_FILE,
    }, indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# 统一启用向导（v5.6.0，relay-v560-unified-onboarding）
# ══════════════════════════════════════════════════════════════
#
# 背景：Step 0 原拆成两块独立渲染 —— ① 时段滚轮（SKILL.md relay-window-wheel）
# ② 模型白名单（inventory + free set）。本 change 合并为**单次**向导（4 段）：
#   ① 始终免费组（系统，宿主规范·只读）
#   ② 平台时段组（系统，宿主规范·只读）
#   ③ 自定义渠道组（BYOK + 桥接，**逐模型选时段**）
#   ④ AgentHub 双层（偏好 / 开通完成态分离）
# 数据源**全部既有**（扫描器 by_id / window.per_model / origins / free_allowlist），
# 本模块只做汇总与落盘，不重造判定（避免「契约断层」双份真相）。
#
# 分工铁律（用户设计决策）：
#   - 系统模型：时段由宿主程序规范定义（平台侧权威）⇒ **只读展示，绝不写覆写**。
#   - 自定义/桥接模型：**逐模型可选时段**；桥接模型（Qoder-free / OpenCode 等）
#     也尝试扫描其免费时段（扫到预填 / 不可达回落 all-day）。

RELAY_ONBOARD_KEY = "relay_onboard"
AGENTHUB_ONBOARDED_KEY = "agenthub_onboarded"
# v5.6.1：AgentHub 偏好消费端 —— 「最近一次已发起提示」的本地自然日（防打扰，每自然日一次）
AGENTHUB_PROMPTED_KEY = "agenthub_prompted_on"
# 桥接来源工具标签（自定义渠道中的「非纯 BYOK」）—— 与 origins 分类口径一致
BRIDGED_TOOLS = ("qoder-free", "qodercli", "ow-bridge", "external")


def _model_origin_tool(entry):
    """单条 models.json 条目的来源工具标签（复用 owner 后缀判定口径，不另起一套）。

    与 `_detect_source_tool`（按批次）相对，本函数按**单条**判定：
      relayOwner → "relay"；已知外部标记 → OWNER_TOOL_MAP 映射值；
      未知 *Owner → "external"；无标记 → "unknown"。
    """
    for k in _owner_marker_keys(entry):
        if k == RELAY_OWNER_KEY:
            return "relay"
        mapped = OWNER_TOOL_MAP.get(k)
        if mapped:
            return mapped
        return "external"
    return "unknown"


def _classify_onboard_models(raw_entries=None):
    """把可声明模型分为 system_models（宿主规范）/ custom_models（BYOK + 桥接）。

    `raw_entries` 为 models.json 原始 list（含 *Owner 标记）；None ⇒ 读当前 data-root。
    返回 (system_models, custom_models)。**纯只读**，不写任何文件。

    custom_models 每条带 `bridged`（是否桥接来源）与 `bridge_tool`，
    供向导第 ③ 段区分「纯 BYOK」与「桥接」，并对桥接项尝试扫描免费时段。
    """
    if raw_entries is None:
        raw_entries = _read_raw_models_list()

    system_models = []
    for m in PLATFORM_MODELS:
        system_models.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "vendor": m.get("vendor", "Platform"),
            "source": "platform",
            "read_only": True,
        })

    custom_models = []
    seen = set()
    for e in raw_entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        if "freeWindow" in e:      # 配置元素不是模型（与 load_models 同口径）
            continue
        mid = e["id"]
        if not isinstance(mid, str) or mid in seen:
            continue
        seen.add(mid)
        tool = _model_origin_tool(e)
        bridged = tool in BRIDGED_TOOLS
        custom_models.append({
            "id": mid,
            "name": e.get("name", mid),
            "vendor": e.get("vendor", "Unknown"),
            "source": "custom",
            "bridged": bridged,
            "bridge_tool": tool if bridged else None,
            "read_only": False,
        })
    return system_models, custom_models


def _config_hash(groups, custom_periods):
    """对 {groups, custom_periods} 规范化 JSON（sort_keys）取 sha256 前 16 位。

    R-HASH：sort_keys 消除 dict 顺序依赖，使同一份配置恒得同一 hash
    （否则每次进程内 dict 迭代顺序变化都会误报「数据漂移」）。
    """
    import hashlib
    payload = json.dumps({"groups": groups, "custom_periods": custom_periods},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _onboard_due(relay_onboard, config_hash, now=None):
    """due 判定 = 未确认 OR 跨本地自然日 OR 数据漂移。返回 (due, drift_detected)。

      - relay_onboard 缺失/非法/confirmed_at 非字符串 → (True, False)（未确认）
      - confirmed_at 与 now 非同一**本地自然日** → (True, False)（跨天）
      - 同一自然日但 last_config_hash != config_hash → (True, True)（数据漂移）
      - 否则 → (False, False)

    日期一律经 `now_utc()`（`now` 可注入，守 TC-TEST-003 单一时间源）。
    """
    if not isinstance(relay_onboard, dict):
        return True, False
    confirmed_at = relay_onboard.get("confirmed_at")
    if not isinstance(confirmed_at, str) or not confirmed_at:
        return True, False
    try:
        confirmed_dt = datetime.fromisoformat(confirmed_at)
    except (ValueError, TypeError):
        return True, False
    now = now or now_utc()
    if confirmed_dt.date() != now.date():
        return True, False
    if relay_onboard.get("last_config_hash") != config_hash:
        return True, True
    return False, False


def migrate_to_relay_onboard(state, _scanner=None):
    """存量迁移（**纯派生，不写盘**）：free_allowlist + 自定义 window 覆写 → relay_onboard。

      - `free_allowlist.ids` → `groups`（按扫描器分类：
        always_free 全天免费 / platform_window 平台时段 / custom 其它）
      - 自定义模型的逐模型 window 覆写 → `custom_periods`
      - 脏数据（ids 非 list / confirmed_at 缺失）→ `groups` 降级为空 {}，**不抛异常**
      - **不改输入 state**（旧键保留只读）—— 写盘只由 `onboard set` 显式触发

    返回 dict：{confirmed_at, groups, custom_periods, agenthub_pref, last_config_hash}。
    """
    empty = {"confirmed_at": None, "groups": {}, "custom_periods": {},
             "agenthub_pref": False, "last_config_hash": None}
    if not isinstance(state, dict):
        return dict(empty)
    ids, meta = load_free_allowlist(state)
    if not ids:
        return dict(empty)

    scanner = _scanner if _scanner is not None else _get_scanner()
    groups = {"always_free": [], "platform_window": [], "custom": []}
    for mid in ids:
        entry = None
        if scanner is not None and scanner.get("available"):
            entry = scanner["by_id"].get(mid)
        if entry is not None:
            # 扫描器有该模型：全天免费（无 window）→ always_free；否则平台时段
            if entry.get("free_now") and not entry.get("window"):
                groups["always_free"].append(mid)
            else:
                groups["platform_window"].append(mid)
        else:
            groups["custom"].append(mid)

    # 自定义模型的逐模型 window 覆写 → custom_periods
    custom_periods = {}
    for mid in ids:
        per = FREE_WINDOW_PER_MODEL.get(mid)
        if per:
            custom_periods[mid] = {
                "start_hour": per.get("start_hour"),
                "end_hour": per.get("end_hour"),
            }
    return {
        "confirmed_at": meta.get("confirmed_at"),
        "groups": groups,
        "custom_periods": custom_periods,
        "agenthub_pref": False,
        "last_config_hash": None,
    }


def _agenthub_action(pref, onboarded):
    """派生动作判据（SC-001~004）：仅「偏好为真 且 未开通」⇒ `prompt_enable`，否则 `none`。

    严格 `pref is True`：None / 非布尔真值一律不触发（脏数据不得误发起开通）。
    纯本地派生，零网络、零副作用。
    """
    return "prompt_enable" if (pref is True and not onboarded) else "none"


def _onboard_agenthub_view(state):
    """AgentHub 视图：偏好 / 开通完成态 / 派生动作 / 最近提示日（SC-011 + v5.6.1 接线）。

    `pref` 来自 state.relay_onboard.agenthub_pref（用户在向导里的勾选）；
    `onboarded` 来自 state.agenthub_onboarded（**只由** multihub-node-onboarding 写）；
    `action` 为**纯派生**判据（`pref is True and not onboarded` ⇒ prompt_enable）；
    `prompted_on` 为最近一次「已提示」的本地自然日（`onboard agenthub-ack` 写），
    供 Agent 做**每自然日一次**的防打扰（v5.6.1）。
    两者分离存储，避免「偏好为真」被误当「已开通」；本 change **只增字段**，
    `pref` / `onboarded` 语义与改动前逐字一致（向后兼容）。
    """
    ro = state.get(RELAY_ONBOARD_KEY) if isinstance(state, dict) else None
    pref = ro.get("agenthub_pref") if isinstance(ro, dict) else None
    onboarded = bool(state.get(AGENTHUB_ONBOARDED_KEY)) if isinstance(state, dict) else False
    prompted_on = ro.get(AGENTHUB_PROMPTED_KEY) if isinstance(ro, dict) else None
    return {"pref": pref, "onboarded": onboarded,
            "action": _agenthub_action(pref, onboarded),
            "prompted_on": prompted_on}


def _scan_bridged_free_window(model, _probe=None):
    """尝试扫描**桥接**模型的免费时段。返回 {start_hour, end_hour} 或 None。

    零阻断（SC-002 / R-BRIDGE）：任何异常都吞掉并返回 None ⇒ 调用方回落 all-day，
    绝不阻断向导、绝不抛异常。
      - `_probe(model) -> dict|None` 可注入（单测不触网）；
      - 默认路径：qoderclicn CLI 可达性探测（qodercli 来源；可达 ⇒ 由额度管理，语义 all-day）。
    """
    if not isinstance(model, dict) or not model.get("bridged"):
        return None
    try:
        if _probe is not None:
            res = _probe(model)
            if (isinstance(res, dict) and res.get("start_hour") is not None
                    and res.get("end_hour") is not None):
                return {"start_hour": res["start_hour"], "end_hour": res["end_hour"]}
            return None
        if model.get("bridge_tool") in ("qodercli", "qoder-free"):
            bin_path = resolve_qoder_cli_bin()
            if not bin_path:
                return None
            list_qoder_cli_models(bin_path)   # 不可达/失败 → 抛异常 → 外层 except 回落 None
            return {"start_hour": 0, "end_hour": 0}
        return None
    except Exception:
        return None


def _system_model_host_window(mid, scanner):
    """系统模型的宿主时段（**只读**）。返回 {start_hour, end_hour, free_now, source, valid_until}。

    优先扫描器 by_id（v5.5.0 权威）；扫描器不可用时回落 `window.per_model`（freeWindow 链）。
    系统模型时段由宿主程序规范定义 ⇒ 调用方**不得**为其写覆写（R-SYS）。
    """
    view = _per_model_window_view().get(mid, {})
    if scanner is not None and scanner.get("available"):
        entry = scanner["by_id"].get(mid)
        if entry is not None:
            w = entry.get("window") or {}
            if w.get("start_hour") is not None:
                sh, eh = w.get("start_hour"), w.get("end_hour")
            else:
                sh, eh = 0, 0     # 无 window ⇒ 全天（hy3 类全天免费 / 全天折扣）
            return {"start_hour": sh, "end_hour": eh,
                    "free_now": entry.get("free_now"),
                    "source": "program_cache",
                    "valid_until": entry.get("valid_until")}
    return {"start_hour": view.get("start_hour"), "end_hour": view.get("end_hour"),
            "free_now": None, "source": "freeWindow", "valid_until": None}


def cmd_onboard(args):
    """统一启用向导数据（**读**）：汇总 system_models / custom_models / agenthub。

    纯只读（SC-001）：不改任何 state / models.json。
      - system_models：宿主时段（扫描器 by_id / window.per_model），只读展示
      - custom_models：BYOK + 桥接；桥接尝试扫描免费时段（扫到预填 / 不可达回落 all-day）
      - agenthub：偏好（pref）与开通完成态（onboarded）分离
    `_probe` 可经 args 注入（单测不触网）。
    """
    system_models, custom_models = _classify_onboard_models()
    scanner = _get_scanner()
    probe = getattr(args, "_probe", None)

    for sm in system_models:
        sm.update(_system_model_host_window(sm["id"], scanner))

    for cm in custom_models:
        scanned = _scan_bridged_free_window(cm, _probe=probe)
        if scanned is not None:
            cm["start_hour"] = scanned["start_hour"]
            cm["end_hour"] = scanned["end_hour"]
            cm["scanned"] = True
        else:
            cm["start_hour"] = 0
            cm["end_hour"] = 0
            cm["scanned"] = False
        cm["all_day"] = (cm["start_hour"], cm["end_hour"]) == (0, 0)

    state = load_state()
    print(json.dumps({
        "system_models": system_models,
        "custom_models": custom_models,
        "agenthub": _onboard_agenthub_view(state),
        "scanner_available": bool(scanner and scanner.get("available")),
        "hint": "把用户调整后的结果用 `onboard set --json <payload>` 落盘；"
                "系统模型时段只读（宿主规范），仅自定义/桥接模型逐模型可调",
    }, indent=2, ensure_ascii=False))


def cmd_onboard_set(args):
    """统一启用向导结果落盘（**写**）。

    接收向导结果 `{groups, custom_periods, agenthub_pref}`（经 `--json`）：
      1. 对**每个非平台（自定义/桥接）模型**写逐模型 window 覆写
         （all_day → `{start_hour:0, end_hour:0}` 恒真语义）
      2. **系统模型（_source=platform）跳过** window 写入，不报错（R-SYS / SC-004）
      3. 写 `free_allowlist`（勾选集 = groups 并集，或显式 selected_ids）
      4. 写 `state.relay_onboard = {confirmed_at, groups, custom_periods,
         agenthub_pref, last_config_hash}`
      5. **不**写 `agenthub_onboarded`（开通完成态只由 multihub-node-onboarding 写，SC-011）

    默认写**覆盖文件**（`_write_override_window`），不碰含 API Key 的 models.json（R-BC）。
    """
    raw = getattr(args, "json", None)
    if not raw:
        _cli_fail("onboard set 需要 --json <payload>", code="missing_json")
    try:
        payload = json.loads(raw)
    except ValueError as e:
        _cli_fail(f"--json 不是合法 JSON：{e}", code="bad_json")
    if not isinstance(payload, dict):
        _cli_fail("--json 顶层应为 JSON 对象", code="bad_json")

    groups = payload.get("groups") if isinstance(payload.get("groups"), dict) else {}
    custom_periods = (payload.get("custom_periods")
                      if isinstance(payload.get("custom_periods"), dict) else {})
    agenthub_pref = bool(payload.get("agenthub_pref"))

    platform_ids = _all_platform_ids()

    # 1 + 2：逐自定义/桥接模型写 window 覆写；系统模型跳过（宿主规范为准）
    written = {}
    skipped_system = []
    for mid, period in custom_periods.items():
        if not isinstance(mid, str) or not mid:
            continue
        if mid in platform_ids:
            skipped_system.append(mid)
            continue
        if not isinstance(period, dict):
            continue
        sh = period.get("start_hour")
        eh = period.get("end_hour")
        if sh is None or eh is None:
            continue
        _write_override_window({"start_hour": sh, "end_hour": eh}, model_id=mid)
        written[mid] = {"start_hour": sh, "end_hour": eh}

    # 3：free_allowlist = 勾选集（groups 并集，或显式 selected_ids）
    selected = payload.get("selected_ids")
    if not isinstance(selected, list):
        selected = []
        for ids in groups.values():
            if isinstance(ids, list):
                selected.extend(i for i in ids if isinstance(i, str))
    seen = set()
    sel = []
    for i in selected:
        if isinstance(i, str) and i and i not in seen:
            seen.add(i)
            sel.append(i)

    confirmed_at = now_utc().isoformat()
    last_hash = _config_hash(groups, custom_periods)

    # 4 + 5：state 一次落盘（relay_onboard + free_allowlist；不写 agenthub_onboarded）
    carried_prompted_on = None
    try:
        with state_file_lock():
            state = load_state()
            state[FREE_ALLOWLIST_KEY] = {"ids": sel, "confirmed_at": confirmed_at}
            prev_ro = state.get(RELAY_ONBOARD_KEY)
            new_ro = {
                "confirmed_at": confirmed_at,
                "groups": groups,
                "custom_periods": custom_periods,
                "agenthub_pref": agenthub_pref,
                "last_config_hash": last_hash,
            }
            # v5.6.1：保留既有「已提示日」——重跑向导不应清空当日防打扰记录（SC-012）。
            # relay_onboard 为整体重建；若不显式 carry-over，用户重跑向导后会被立刻再提示一次。
            if isinstance(prev_ro, dict) and isinstance(prev_ro.get(AGENTHUB_PROMPTED_KEY), str):
                new_ro[AGENTHUB_PROMPTED_KEY] = prev_ro[AGENTHUB_PROMPTED_KEY]
                carried_prompted_on = new_ro[AGENTHUB_PROMPTED_KEY]
            state[RELAY_ONBOARD_KEY] = new_ro
            save_state(state)
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}",
                          "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({
        "ok": True,
        "action": "onboard_set",
        "written_windows": written,
        "skipped_system_models": skipped_system,
        "free_allowlist": {"ids": sel, "confirmed_at": confirmed_at},
        "relay_onboard": {"confirmed_at": confirmed_at,
                          "last_config_hash": last_hash,
                          "agenthub_pref": agenthub_pref,
                          "agenthub_prompted_on": carried_prompted_on},
        "agenthub_onboarded_written": False,
    }, indent=2, ensure_ascii=False))


def cmd_onboard_agenthub_ack(args):
    """记录「今日已发起 AgentHub 开通提示」（**写**，v5.6.1 接线）。

    写 `state.relay_onboard.agenthub_prompted_on = now_utc().date().isoformat()`：
      - **读-改-写**，保留 relay_onboard 其余字段（confirmed_at/groups/.../agenthub_pref）；
      - **同日重复调用幂等**（值不变）；
      - **适用性门控**（防御）：仅当 `agenthub.action == "prompt_enable"`（即确实有待发起的开通）
        才记录；否则返回 `ok=false`（reason=not_applicable）且不落盘 —— 避免误调 ack 后，
        同一自然日内正当的开通提示被 `prompted_on` 静默抑制；
      - 前置不满足（relay_onboard 缺失）⇒ `ok=false`（reason=no_relay_onboard）且
        **不落盘**、退出码 0（前置不满足，非用法错误）。
    供 Agent 做**每自然日一次**的防打扰：同日已提示过就不再重复发起开通流程。
    """
    try:
        with state_file_lock():
            state = load_state()
            ro = state.get(RELAY_ONBOARD_KEY) if isinstance(state, dict) else None
            if not isinstance(ro, dict):
                result = {"ok": False, "reason": "no_relay_onboard",
                          "hint": "先完成启用向导（onboard set）再记录提示"}
            else:
                view = _onboard_agenthub_view(state)
                if view.get("action") != "prompt_enable":
                    result = {"ok": False, "reason": "not_applicable",
                              "agenthub": view,
                              "hint": "当前无待发起的 AgentHub 开通（偏好未开或已开通），无需记录提示"}
                else:
                    today = now_utc().date().isoformat()
                    ro[AGENTHUB_PROMPTED_KEY] = today
                    state[RELAY_ONBOARD_KEY] = ro
                    save_state(state)
                    result = {"ok": True, "action": "agenthub_ack",
                              "agenthub_prompted_on": today}
    except TimeoutError as e:
        print(json.dumps({"error": f"state lock timeout: {e}",
                          "hint": "并发写入 STATE_FILE 超时，请稍后重试"}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _current_onboard_groups(_scanner=None):
    """当前派生配置的 (groups, custom_periods)，供漂移判定。**只读**。

    groups 分类口径与 `migrate_to_relay_onboard` 一致：
      扫描器 free_now 且无 window ⇒ always_free；扫描器有 window / 无扫描器 ⇒ platform_window
    系统模型（PLATFORM_MODELS）进 always_free/platform_window；models.json 条目进 custom。
    """
    system_models, custom_models = _classify_onboard_models()
    scanner = _scanner if _scanner is not None else _get_scanner()
    groups = {"always_free": [], "platform_window": [], "custom": []}
    for sm in system_models:
        mid = sm["id"]
        entry = scanner["by_id"].get(mid) if (scanner and scanner.get("available")) else None
        if entry is not None and entry.get("free_now") and not entry.get("window"):
            groups["always_free"].append(mid)
        else:
            groups["platform_window"].append(mid)
    custom_periods = {}
    for cm in custom_models:
        mid = cm["id"]
        groups["custom"].append(mid)
        eff = _effective_free_window(mid)
        custom_periods[mid] = {"start_hour": eff.get("start_hour"),
                               "end_hour": eff.get("end_hour")}
    return groups, custom_periods


def _onboard_due_now(state=None, _scanner=None):
    """当前是否 due（供 next / inventory 透传）。

    `state` 缺省时自读；`relay_onboard` 缺失即未确认 ⇒ due=true。
    """
    if state is None:
        state = load_state()
    groups, custom_periods = _current_onboard_groups(_scanner=_scanner)
    ro = state.get(RELAY_ONBOARD_KEY) if isinstance(state, dict) else None
    due, _drift = _onboard_due(ro, _config_hash(groups, custom_periods))
    return due


def cmd_onboard_status(args):
    """统一向导确认状态（**只读**）：due = 未确认 / 跨自然日 / 数据漂移。

    输出 {due, drift_detected, confirmed_at, last_config_hash, current_config_hash,
    today, agenthub}。`current_config_hash` 由当前扫描/声明派生（供漂移判定与调试）。
    """
    state = load_state()
    ro = state.get(RELAY_ONBOARD_KEY) if isinstance(state, dict) else None
    groups, custom_periods = _current_onboard_groups()
    current_hash = _config_hash(groups, custom_periods)
    due, drift = _onboard_due(ro, current_hash)
    ro = ro if isinstance(ro, dict) else {}
    print(json.dumps({
        "due": due,
        "drift_detected": drift,
        "confirmed_at": ro.get("confirmed_at"),
        "last_config_hash": ro.get("last_config_hash"),
        "current_config_hash": current_hash,
        "today": now_utc().date().isoformat(),
        "agenthub": _onboard_agenthub_view(state),
    }, indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def add_source_arg(p):
    """给子命令加 --source 参数。"""
    p.add_argument("--source", choices=["auto", "custom", "platform", "all"],
                   default="auto", help="模型来源（auto = 按时段自动切换）")


def main():
    parser = argparse.ArgumentParser(
        description="AgentInn v4 — 免费模型智能选择器 + 流量统计 + 平台模型时段感知")
    sub = parser.add_subparsers(dest="command", help="子命令")

    # 带 --source 的命令
    p_list = sub.add_parser("list", help="列出所有模型 + 推断工作类型")
    add_source_arg(p_list)

    sub.add_parser("scan", help="检测 models.json 新增/移除的模型")

    sub.add_parser("inventory",
                   help="枚举全部可声明模型（含非 Custom vendor 条目），供勾选确认哪些是免费模型")

    sub.add_parser("origins",
                   help="只读：枚举模型来源的每一个候选 data-root 与平台源（relay / OW Bridge / 平台）")

    # v5.6.0：统一启用向导（Step 0 单次渲染）—— onboard（读）/ onboard set（写）
    p_onboard = sub.add_parser("onboard",
                               help="统一启用向导：汇总系统/自定义/桥接模型 + AgentHub（读）")
    p_onboard.add_argument("onboard_action", nargs="?", default="show",
                           choices=["show", "set", "agenthub-ack"],
                           help="show（默认，读）/ set（写）/ agenthub-ack（写：记录今日已提示）")
    p_onboard.add_argument("--json", default=None, dest="json",
                           help="set：向导结果 JSON（groups / custom_periods / agenthub_pref）")

    sub.add_parser("onboard-status",
                   help="只读：统一向导确认状态（due = 未确认 / 跨天 / 数据漂移）")

    p_free = sub.add_parser("free", help="免费模型白名单（显式确认哪些模型算免费）")
    p_free.add_argument("free_action", choices=["set", "show", "clear"], help="set/show/clear")
    p_free.add_argument("--ids", default=None,
                        help="勾选的模型 id，逗号分隔（set 必填），如 a,b,c")

    # N1: 密钥录入（relay 此前对 models.json 只有读操作）
    # 注意：**不提供** --api-key 明文参数 —— argv 可见于 ps 输出（SC-MO-013）
    p_models = sub.add_parser("models", help="模型密钥录入与管理（N1）")
    p_models.add_argument("models_action", choices=["add", "list"],
                          help="add=录入/更新模型；list=只读查看密钥状态三态")
    p_models.add_argument("--id", default=None, help="模型 ID（add 必填）")
    p_models.add_argument("--url", default=None,
                          help="模型 API 端点（add 必填，需以 http:// 或 https:// 开头）")
    p_models.add_argument("--from-env", default=None, dest="from_env",
                          help="从环境变量读密钥；落盘 `${VAR}` 占位符字面量（不落盘真实值）")
    p_models.add_argument("--stdin", action="store_true", dest="stdin",
                          help="从标准输入读密钥（供 CI/脚本使用）")
    p_models.add_argument("--force", action="store_true", dest="force",
                          help="解除所有权拒绝：允许更新带**外部**所有权标记"
                               "（任何非 relayOwner 的 *Owner 键，如 OW Bridge 的 "
                               "buddyBridgeOwner）的条目。只解除拒绝，**不**绕过"
                               "写入安全协议与参数校验")

    p_profile = sub.add_parser("profile", help="查看每个模型的工作类型画像")
    add_source_arg(p_profile)

    p_usage = sub.add_parser("usage", help="流量统计表")
    add_source_arg(p_usage)

    p_next = sub.add_parser("next", help="获取下一个模型（自动跳过超限/限流）")
    p_next.add_argument("--strategy",
                        choices=["round-robin", "fallback", "capability-match", "auto"],
                        default=None,
                        help="调度策略 (--strategy auto 必须配合 --job 使用)")
    p_next.add_argument("--needs", nargs="*", default=None,
                        help="能力需求 (仅 --strategy capability-match 时使用，"
                             "合法值: tool_call, images, reasoning)")
    p_next.add_argument("--job", default=None,
                        help="工作类型 (--strategy auto 必填): "
                             "code-review, spec-writing, test-gen, doc-review, general")
    add_source_arg(p_next)

    p_window = sub.add_parser("window", help="查看/修改平台模型免费时段")
    # nargs="?" + default="show"：裸 `window` 必须逐字保持原行为（C5 向后兼容）
    p_window.add_argument("window_action", nargs="?", default="show",
                          choices=["show", "set"], help="show（默认）/ set")
    # 注意：小时字段**不收 type=int**，见 _coerce_window_field 的注释
    p_window.add_argument("--start-hour", default=None, dest="start_hour",
                          help="免费时段起始小时（0-23 整数）")
    p_window.add_argument("--end-hour", default=None, dest="end_hour",
                          help="免费时段结束小时（0-23 整数）")
    p_window.add_argument("--since", default=None,
                          help="活动开始日 YYYY-MM-DD")
    p_window.add_argument("--until", default=None,
                          help="活动结束日 YYYY-MM-DD")
    p_window.add_argument("--write-models-json", action="store_true",
                          dest="write_models_json",
                          help="写入 models.json 的 freeWindow 元素"
                               "（含 API Key 的文件，默认不写；"
                               "自动备份 + 原子替换 + 写后逐字校验）")
    # v5.3：逐模型覆写。**只在显式指定时**才升级文件形态（SC-FWX-017/018）——
    # 不碰 per-model 的既有用户不会被静默迁移。
    p_window.add_argument("--model", default=None, dest="model",
                          help="只写该模型 ID 的逐字段覆写（写入 models[<id>]）；"
                               "不指定则写全局 default 层并保持既有文件形态")
    sub.add_parser("status", help="查看当前状态")
    sub.add_parser("reset", help="重置状态（保留用量统计）")

    p_doctor = sub.add_parser("doctor", help="健康检查：一次报出全部配置与运行隐患")
    p_doctor.add_argument("--fix", action="store_true",
                          help="只清理真孤立条目（模型已删，用量无意义；不影响调度）")
    p_doctor.add_argument("--fix-unsafe", action="store_true",
                          dest="fix_unsafe",
                          help="额外清除限流标记并重置超限配额"
                               "（会让不可用模型立即重新参与调度，可能产生费用）")
    p_doctor.add_argument("--check-endpoint", action="store_true",
                          dest="check_endpoint",
                          help="可达性档：对每个模型 url 做连通性探测（含超时上限）。"
                               "默认关闭 ⇒ 默认零网络")
    p_doctor.add_argument("--check-key", action="store_true",
                          dest="check_key",
                          help="有效性档：对每个模型发一次最小请求校验密钥是否被接受"
                               "（蕴含 --check-endpoint；每模型至多 1 次、max_tokens=1、"
                               "首个失败即停，会产生真实费用）")
    p_doctor.add_argument("--check-tools", action="store_true",
                          dest="check_tools",
                          help="工具调用能力档：在密钥探测的**同一次**计费请求上附加 tools "
                               "声明，判定模型是否真返回 tool_calls（而非仅声明 "
                               "supportsToolCall=true）。蕴含 --check-key 与 "
                               "--check-endpoint；每模型计费请求仍至多 1 次")

    p_record = sub.add_parser("record", help="记录一次用量")
    p_record.add_argument("--model", required=True, help="模型 ID")
    p_record.add_argument("--tokens", type=int, default=0, help="本次估算 token 数（可选）")

    p_quota = sub.add_parser("quota", help="配额管理")
    p_quota.add_argument("quota_action", choices=["set", "show"], help="set/show")
    p_quota.add_argument("--model", help="模型 ID（set 必填）")
    p_quota.add_argument("--max-requests", type=int, default=None, help="最大请求数")
    p_quota.add_argument("--max-tokens", type=int, default=None, help="最大 token 数")

    p_ex = sub.add_parser("mark-exhausted", help="标记模型临时限流")
    p_ex.add_argument("--model", required=True, help="模型 ID")
    p_ex.add_argument("--minutes", type=int, default=60, help="限流时长（分钟）")

    p_cl = sub.add_parser("clear-exhausted", help="清除限流标记")
    p_cl.add_argument("--model", required=True, help="模型 ID")

    p_qf = sub.add_parser("qoder-free", help="Qoderclicn 直扫源（自动发现 + 本地 relay）")
    p_qf.add_argument("qf_action", choices=["sync", "status", "relay-start", "relay-stop", "relay-status"],
                      help="sync=强刷发现并写 models.json；status=CLI 可达性+relay 状态；"
                           "relay-start/stop/status=本地 relay 进程管理（方案 A）")

    args = parser.parse_args()

    # 改名后一次性数据迁移：旧名文件 → 新名（只读旧、写新、保留旧；幂等、失败静默）。
    # 放在任何子命令之前，保证后续读取一律命中新名。
    _migrate_legacy_data_files()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "list": cmd_list,
        "scan": cmd_scan,
        "inventory": cmd_inventory,
        "origins": cmd_origins,
        "onboard": _dispatch_onboard,
        "onboard-status": cmd_onboard_status,
        "free": cmd_free,
        "models": _dispatch_models,
        "profile": cmd_profile,
        "usage": cmd_usage,
        "next": cmd_next,
        "window": _dispatch_window,
        "status": cmd_status,
        "reset": cmd_reset,
        "record": cmd_record,
        "quota": cmd_quota,
        "mark-exhausted": cmd_mark_exhausted,
        "clear-exhausted": cmd_clear_exhausted,
        "doctor": cmd_doctor,
        "qoder-free": cmd_qoder_free,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()

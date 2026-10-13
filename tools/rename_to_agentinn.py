#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rename_to_agentinn.py — 品牌改名替换引擎（一次性迁移工具）。

设计依据（本机 rename-refactor skill 规程）：
  1. **单次扫描**：用一条正则 alternation + 回调，对原串只扫一遍。
     禁止逐条 str.replace —— 前一条规则的产物会进入后一条的输入域。
  2. **左边界 `(?<![A-Za-z])`**：防止规则匹配既有产物（重复执行时二次命中）。
  3. **幂等**：对已改名文本重复执行结果不变（内置 --selftest 验证）。

注：本文件刻意**不出现旧名字面**（旧名以拼接构造），以便「无残留」守卫断言可覆盖引擎自身。

用法：
  python rename_to_agentinn.py --check        # 只检查，有差异则退出码 1
  python rename_to_agentinn.py --apply        # 就地替换（幂等，可重复跑）
  python rename_to_agentinn.py --selftest     # 幂等自测
  python rename_to_agentinn.py --apply --root <skill_dir>
"""
import argparse
import io
import os
import re
import sys

# ── 旧名以拼接构造（避免本文件被「无残留」断言检出）──────────────────
_OLD_KEBAB = "free-" + "model-relay"
_OLD_TITLE = "Free " + "Model Relay"
_OLD_CN = "免费模型" + "子代理接棒器"

_NEW = "agentinn"
_NEW_TITLE = "AgentInn"
_NEW_CN = "AgentInn 多模型接棒器"

# ── 规则表：**长串在前**；每条加左边界 ────────────────────────────────
# 说明：
#   · 只改「品牌标识」三类变体；不改通用词 `relay`（relay_instruction.md / [relay-*] /
#     relayOwner）——它们是协议前缀与通用词，改名会破坏 AI↔skill 协议与 owner 契约。
#   · 不改 `FMR_*` 环境变量与 `fmr-*` 测试文件名——内部缩写/外部接口，非品牌标识。
RULES = [
    (_OLD_KEBAB, _NEW),
    (_OLD_TITLE, _NEW_TITLE),
    (_OLD_CN, _NEW_CN),
]

_PATTERN = re.compile("|".join("(?<![A-Za-z])(?:%s)" % re.escape(p) for p, _ in RULES))


def _repl(m):
    got = m.group(0)
    for pat, new in RULES:
        if got == pat:
            return new
    return got  # 不可达（防御）


def apply_rules(text):
    """对文本执行单次扫描替换（幂等）。"""
    return _PATTERN.sub(_repl, text)


# 默认处理的仓库内文件（相对 skill 根）
DEFAULT_FILES = [
    "SKILL.md",
    "relay_instruction.md",
    os.path.join("scripts", "pick_model.py"),
]


def find_skill_root():
    """定位 skill 根：优先新名目录，回退旧名目录（改名前后均可）。"""
    home = os.path.expanduser("~")
    for name in (_NEW, _OLD_KEBAB):
        p = os.path.join(home, ".workbuddy-ai", "skills", name)
        if os.path.isdir(p):
            return p
    return None


def process(root, files, apply=False):
    changed = []
    for rel in files:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with io.open(path, "r", encoding="utf-8", newline="") as f:
            original = f.read()
        updated = apply_rules(original)
        if updated != original:
            changed.append(rel)
            if apply:
                with io.open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(updated)
    return changed


def selftest():
    """幂等自测：对已改名文本重复执行不变；且左边界不误伤复合词。"""
    for t in (_NEW, _NEW_TITLE, _NEW_CN, _NEW + "-state.json", _NEW + "_instruction.md"):
        assert apply_rules(t) == t, "NOT IDEMPOTENT: %r -> %r" % (t, apply_rules(t))
    assert apply_rules(_OLD_KEBAB) == _NEW
    assert apply_rules(_OLD_TITLE) == _NEW_TITLE
    assert apply_rules(_OLD_CN) == _NEW_CN
    assert apply_rules("my" + _OLD_KEBAB) == "my" + _OLD_KEBAB  # 左边界
    print("selftest OK: idempotent + left-boundary + forward mapping")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，有差异则退出码 1")
    ap.add_argument("--apply", action="store_true", help="就地替换")
    ap.add_argument("--selftest", action="store_true", help="幂等自测")
    ap.add_argument("--root", default=None, help="skill 根（默认自动定位）")
    ap.add_argument("--file", action="append", default=None, help="仅处理指定文件（可多次）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    root = args.root or find_skill_root()
    if not root:
        print("[FAIL] 找不到 skill 根")
        return 2
    files = args.file or DEFAULT_FILES

    changed = process(root, files, apply=args.apply)
    if changed:
        print("需要替换的文件：")
        for c in changed:
            print("  - %s" % c)
        if not args.apply:
            print("[CHECK] 存在未改名文件（退出码 1）")
            return 1
        print("[APPLY] 已就地替换（%d 个文件）" % len(changed))
    else:
        print("[OK] 无需替换（已改名或幂等）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

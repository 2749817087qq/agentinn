#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qodercli_relay.py —— agentinn 的 qoderclicn 本地 relay（方案 A）。

设计原则（沿用 DSH connector 思路）：**复用源产品自己的鉴权客户端**，
绝不逆向 qoderclicn 的 access_token。每个 OpenAI 兼容请求落到本 relay 后，
本 relay 直接 shell-out 到官方 `qoderclicn -p`（qoderclicn 自己持有有效会话去打网关），
把 stdout 整理成 OpenAI 形状的 chat.completion 返回。

宿主（WorkBuddy）调用模型时，把 qodercli 模型的 url 指向
    http://127.0.0.1:<port>/v1
apiKey 随便填（本 relay 忽略 Authorization，鉴权由 qoderclicn 会话负责）。

已知 MVP 限制（非阻断）：
- qoderclicn `-p` 是一次性补全，多轮历史仅取「最后一条 user」作 query，system 作 --system-prompt；
  更早的 user/assistant 轮次不进入上下文。
- 不支持 tools / function calling（CLI 不暴露）。
- 流式：缓冲完成后发单个 SSE chunk + [DONE]（够骗过基础 SSE 客户端，非真流式）。
"""

import argparse
import json
import os
import sys
import time
import uuid
import subprocess
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
QODER_CLI_BIN_CANDIDATES = [
    os.path.join(HOME, ".qoder-cn", "bin", "qoderclicn", "qoderclicn.exe"),
    os.path.join(HOME, ".qoder", "bin", "qoderclicn", "qoderclicn.exe"),
    "qoderclicn",
]
DEFAULT_PORT = 8799
DEFAULT_HOST = "127.0.0.1"
REQUEST_TIMEOUT = 180
CREATE_NO_WINDOW = 0x08000000  # Windows: 不弹控制台窗口


def resolve_bin():
    for c in QODER_CLI_BIN_CANDIDATES:
        if os.path.isfile(c):
            return c
    import shutil
    return shutil.which("qoderclicn")


def _decode_body(raw):
    """请求体按 UTF-8 解析；客户端若误发 GBK 等系统编码，回落 gb18030（GBK 超集）再回落 locale，
    避免整个请求被 500。宿主 WorkBuddy 走标准 UTF-8，此回落仅为健壮性兜底。"""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    import locale
    return raw.decode(locale.getpreferredencoding(), errors="replace")


def build_query(messages):
    """从 OpenAI messages 抽 system + 最后一条 user。返回 (sys_text, query)。"""
    sys_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    sys_text = "\n".join(p for p in sys_parts if p) or None
    user_msgs = [m for m in messages if m.get("role") == "user"]
    query = (user_msgs[-1].get("content", "") if user_msgs else "") or ""
    return sys_text, query


def _decode_cli_output(raw):
    """qoderclicn 在 Windows 控制台以系统 codepage（GBK/cp936）输出中文。
    优先 utf-8，再 gb18030（GBK 超集，覆盖中文 Windows 控制台输出），最后 locale 兜底；
    这样即便宿主在 PYTHONUTF8=1 下运行也能正确还原中文，绝不让 reader 线程崩。"""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    import locale
    return raw.decode(locale.getpreferredencoding(), errors="replace")


def qoder_complete(bin_path, model, sys_text, query, max_tokens):
    args = [bin_path, "-p", "-m", model]
    if sys_text:
        args += ["--system-prompt", sys_text]
    if max_tokens:
        args += ["--max-output-tokens", str(max_tokens)]
    args.append(query)
    t0 = time.time()
    # 以 bytes 读取（避免 text=True 在 PYTHONUTF8 环境下把 GBK 输出当 utf-8 崩 reader 线程）
    proc = subprocess.run(
        args, capture_output=True,
        timeout=REQUEST_TIMEOUT, creationflags=CREATE_NO_WINDOW,
    )
    out = _decode_cli_output(proc.stdout or b"")
    return out, proc.returncode, (time.time() - t0)


def _send_json(handler, code, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_sse(handler, obj):
    handler.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    bin_path = None

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            if path in ("/v1/models", "/models"):
                _send_json(self, 200, {
                    "object": "list",
                    "data": [],
                    "note": "model list is provided by agentinn (models.json), not this relay",
                })
                return
            _send_json(self, 404, {"error": "not found: %s" % path})
            return

        try:
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            req = json.loads(_decode_body(raw) or "{}")
        except Exception as e:
            _send_json(self, 400, {"error": "bad request: %s" % e})
            return

        model = req.get("model") or "Auto"
        messages = req.get("messages") or []
        max_tokens = req.get("max_tokens") or req.get("max_output_tokens")
        stream = bool(req.get("stream"))
        sys_text, query = build_query(messages)
        if not query:
            _send_json(self, 400, {"error": "no user message in request"})
            return

        try:
            out, rc, dt = qoder_complete(self.bin_path, model, sys_text, query, max_tokens)
        except subprocess.TimeoutExpired:
            _send_json(self, 504, {"error": "qoderclicn timeout (%ds)" % REQUEST_TIMEOUT})
            return
        except Exception as e:
            _send_json(self, 500, {"error": "relay error: %s" % e})
            return

        if rc != 0:
            _send_json(self, 502, {"error": "qoderclicn rc=%d" % rc, "detail": out[:500]})
            return

        content = (out or "").rstrip("\n")
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            _send_sse(self, {
                "id": "chatcmpl-" + uuid.uuid4().hex[:12],
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
            })
            _send_sse(self, {"id": "x", "object": "chat.completion.chunk",
                             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            _send_sse(self, "[DONE]")
            return

        _send_json(self, 200, {
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1},
            "relay_meta": {"backend": "qoderclicn", "ms": int(dt * 1000)},
        })

    def log_message(self, *a):  # 静默
        pass

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/v1/models", "/models"):
            _send_json(self, 200, {
                "object": "list",
                "data": [],
                "note": "model list is provided by agentinn (models.json), not this relay",
            })
            return
        _send_json(self, 404, {"error": "not found: %s" % path})


def main():
    ap = argparse.ArgumentParser(description="agentinn qoderclicn OpenAI-compatible relay")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bin", default=None, help="qoderclicn binary path override")
    args = ap.parse_args()

    bin_path = args.bin or resolve_bin()
    if not bin_path:
        print("ERROR: qoderclicn not found in candidates", file=sys.stderr)
        sys.exit(2)
    Handler.bin_path = bin_path
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("qodercli relay listening on http://%s:%d/v1  (bin=%s)" %
          (args.host, args.port, bin_path), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()

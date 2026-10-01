"""Read-only latency investigation; real Studio code, deterministic HTTP upstream."""
import argparse
import asyncio
import collections
import contextlib
import json
import os
import socket
import ssl
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--source", default=str(Path(__file__).parent))
parser.add_argument("--repeats", type=int, default=8)
parser.add_argument("--upstream-port", type=int)
parser.add_argument("--cached-client-context", action="store_true")
parser.add_argument("--full-app", action="store_true")
args = parser.parse_args()
os.environ["UNSLOTH_STUDIO_HOME"] = str(Path(args.source) / "probe-home")
os.environ["UNSLOTH_STUDIO_DISABLE_DEVICE_PROBE"] = "1"
os.environ["UNSLOTH_ALLOW_CPU"] = "1"
os.environ["UNSLOTH_IS_PRESENT"] = "1"
sys.path.insert(0, str(Path(args.source) / "studio/backend"))
if args.full_app:
    os.environ["UNSLOTH_API_ONLY"] = "1"
    os.environ["UNSLOTH_STUDIO_DISABLE_TORCH_WARM"] = "1"
    from utils.native_tls import activate_native_tls
    activate_native_tls()
import httpx
from fastapi import FastAPI
from core.inference import llama_cpp

# Importing the router constructs a process owner. Suppress only orphan reaping;
# this diagnostic must never interfere with a user's running llama-server.
with patch.object(llama_cpp.LlamaCppBackend, "_kill_orphaned_servers", return_value=0):
    from routes import inference
from auth.authentication import get_current_subject

events = collections.defaultdict(list)
upstream_calls = collections.Counter()

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        upstream_calls[self.path] += 1
        if self.path.endswith("/input_tokens"):
            value = {"input_tokens": 15}
        elif self.path == "/apply-template":
            value = {"prompt": "A tiny rendered prompt"}
        elif self.path == "/tokenize":
            value = {"tokens": list(range(15))}
        elif self.path == "/v1/chat/completions":
            value = {"id": "test", "object": "chat.completion", "created": 1,
                     "model": "probe.gguf", "choices": [{"index": 0, "message": {
                         "role": "assistant", "content": "Hello"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 15, "completion_tokens": 1, "total_tokens": 16}}
            if body.get("stream"):
                chunks = [{"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
                          {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": value["usage"]}]
                data = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        else:
            raise AssertionError(self.path)
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

def timed(name, fn):
    def inner(*a, **kw):
        t = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            events[name].append((time.perf_counter() - t) * 1000)
    return inner

def summarize(samples):
    return {"n": len(samples), "median_ms": round(statistics.median(samples), 3),
            "min_ms": round(min(samples), 3), "max_ms": round(max(samples), 3)}

server = None
if not args.upstream_port:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
backend = llama_cpp.LlamaCppBackend(manages_processes=False)
backend._process = object()
backend._healthy = True
backend._port = args.upstream_port or server.server_port
backend._model_identifier = "probe.gguf"
backend._model_path = "probe.gguf"
backend._context_length = 4096
backend._effective_parallel_slots = 4
inference._llama_cpp_backend = backend
request_headers = {}
if args.full_app:
    import secrets
    import main
    from auth import storage
    if not storage.get_user_and_secret(storage.DEFAULT_ADMIN_USERNAME):
        storage.create_initial_user(storage.DEFAULT_ADMIN_USERNAME, secrets.token_hex(20), secrets.token_hex(32))
    key, _ = storage.create_api_key(storage.DEFAULT_ADMIN_USERNAME, "isolated latency investigation")
    request_headers = {"Authorization": "Bearer " + key}
    app = main.app
else:
    app = FastAPI()
    app.include_router(inference.router, prefix="/v1")
    app.dependency_overrides[get_current_subject] = lambda: "tester"

async def run():
    result = {}
    async with httpx.AsyncClient(base_url=backend.base_url, trust_env=False) as direct:
        samples = []
        for i in range(args.repeats + 1):
            t = time.perf_counter()
            response = await direct.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 8, "stream": False})
            elapsed = (time.perf_counter() - t) * 1000
            assert response.status_code == 200, response.text
            if i:
                samples.append(elapsed)
        result["direct_chat"] = summarize(samples)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe") as client:
        for label, path, payload in [
            ("count", "/v1/chat/count_tokens", {"messages": [{"role": "user", "content": "Hello"}]}),
            ("chat_nonstream", "/v1/chat/completions", {"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 8, "stream": False}),
            ("chat_stream", "/v1/chat/completions", {"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 8, "stream": True}),
        ]:
            events.clear()
            upstream_calls.clear()
            samples = []
            for i in range(args.repeats + 1):
                t = time.perf_counter()
                response = await client.post(path, json=payload, headers=request_headers)
                elapsed = (time.perf_counter() - t) * 1000
                assert response.status_code == 200, (label, response.status_code, response.text)
                if not args.upstream_port:
                    if label == "count":
                        assert response.json()["input_tokens"] == 15, response.text
                    elif label == "chat_nonstream":
                        assert response.json()["choices"][0]["message"]["content"] == "Hello", response.text
                    else:
                        assert 'Hello' in response.text and 'data: [DONE]' in response.text, response.text
                if i:
                    samples.append(elapsed)
                else:
                    cold = elapsed
                    events.clear()
                    upstream_calls.clear()
            result[label] = {**summarize(samples), "cold_ms": round(cold, 3),
                             "components": {k: summarize(v) for k, v in events.items()},
                             "upstream_calls": dict(upstream_calls)}
    return result

try:
    with contextlib.ExitStack() as stack:
        if args.cached_client_context:
            import certifi
            shared_context = ssl.create_default_context(cafile=certifi.where())
            original_init = httpx.Client.__init__
            def cached_init(self, *a, **kw):
                kw.setdefault("verify", shared_context)
                return original_init(self, *a, **kw)
            stack.enter_context(patch.object(httpx.Client, "__init__", cached_init))
        for target, name in [(ssl, "create_default_context"), (socket, "getaddrinfo"), (httpx.Client, "__init__"),
                             (llama_cpp.LlamaCppBackend, "count_chat_tokens")]:
            stack.enter_context(patch.object(target, name, timed(name, getattr(target, name))))
        results = asyncio.run(run())
    print(json.dumps({"source": args.source, "python": sys.version, "openssl": ssl.OPENSSL_VERSION,
                      "httpx": httpx.__version__, "cached_client_context": args.cached_client_context,
                      "full_app": args.full_app, "ssl_context_class": str(ssl.SSLContext),
                      "results": results}, indent=2))
finally:
    backend._process = None
    backend._healthy = False
    if server is not None:
        server.shutdown()
        server.server_close()

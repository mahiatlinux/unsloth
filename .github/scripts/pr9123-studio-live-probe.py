#!/usr/bin/env python3
"""Live Studio probe for unslothai/unsloth PR 9123.

Asserts the behaviour the PR claims, on a real install, in a browser: while a reply is
streaming and the composer holds queueable text, the running composer must offer BOTH
"Stop generating" and "Queue message". Before the fix the two shared one slot and typing
removed Stop, leaving a streaming reply with no way to cancel it.

The reply is produced by a small OpenAI-compatible endpoint the probe serves on loopback
and registers as a custom provider, so the stream is paced (a token every 400 ms) and long
enough to photograph without a GPU, a download, or a provider key.

Prints PASS/FAIL lines and writes screenshots into STUDIO_ARTIFACT_DIR. Never prints the
bootstrap password or any token.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from studio_test_kit.ui import open_chat

MODEL_ID = "pr9123-slow-stream"
QUEUED_TEXT = "and then summarise it in one line"
_CHUNKS = 600
_CHUNK_DELAY_S = 0.4


def pass_log(message: str) -> None:
    print(f"PASS {message}", flush=True)


def warn(message: str) -> None:
    print(f"WARN {message}", flush=True)


def fail(message: str) -> None:
    print(f"FAIL {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_unsloth_bin(home: Path) -> Path:
    candidates = [
        home / "bin" / "unsloth",
        home / "bin" / "unsloth.exe",
        home / "unsloth_studio" / "bin" / "unsloth",
        home / "unsloth_studio" / "Scripts" / "unsloth.exe",
    ]
    candidates.extend(home.glob(".venv*/*/unsloth"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    fail(f"could not find unsloth CLI under {home}")


def start_studio(home: Path, log_path: Path, port: int) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    env = {**os.environ, "UNSLOTH_STUDIO_HOME": str(home)}
    return subprocess.Popen([str(find_unsloth_bin(home)), "studio", "-p", str(port)],
                            stdout=handle, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for_health(base_url: str, timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=10) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 -- the server is still coming up
            last = str(exc)
        time.sleep(2)
    fail(f"Studio never became healthy on {base_url}: {last}")


def read_bootstrap_password(home: Path) -> str:
    for rel in ("auth/.bootstrap_password", ".bootstrap_password"):
        path = home / rel
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    fail("could not read the Studio bootstrap password from the install home")


def post_json(url: str, payload: dict, token: str | None = None, timeout: int = 120) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def authenticate(base_url: str, home: Path) -> tuple[str, str]:
    """Log in with the bootstrap credential and rotate it.

    The rotation is not optional: until it happens every authenticated route answers 403
    with "Password change required".
    """
    bootstrap = read_bootstrap_password(home)
    rotated = "Pr9123-" + os.urandom(8).hex()
    tokens = post_json(f"{base_url}/api/auth/login",
                       {"username": "unsloth", "password": bootstrap})
    tokens = post_json(f"{base_url}/api/auth/change-password",
                       {"current_password": bootstrap, "new_password": rotated},
                       token=tokens["access_token"])
    return tokens["access_token"], tokens.get("refresh_token", "")


class _SlowStreamHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible chat endpoint that streams on a fixed clock."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's spelling
        if urllib.parse.urlparse(self.path).path.endswith("/models"):
            self._json({"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]})
            return
        self._json({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's spelling
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if not path.endswith("/chat/completions"):
            self._json({"error": {"message": "not found"}}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        base = {"id": "pr9123", "object": "chat.completion.chunk", "created": 0,
                "model": MODEL_ID}
        try:
            for index in range(_CHUNKS):
                delta: dict = {"role": "assistant"} if index == 0 else {}
                delta["content"] = f"token {index + 1} "
                chunk = {**base, "choices": [{"index": 0, "delta": delta,
                                              "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(_CHUNK_DELAY_S)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # a closed page or a cancelled run, both normal endings here
            pass


def start_stream_server() -> tuple[ThreadingHTTPServer, int]:
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _SlowStreamHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def register_provider(base_url: str, token: str, stream_port: int) -> str:
    """Save the loopback endpoint as a custom provider and return its id.

    Server-side is the only place that counts: the frontend syncs its provider list down
    from the server and prunes anything planted in localStorage alone.
    """
    created = post_json(f"{base_url}/api/providers/", {
        "provider_type": "custom",
        "display_name": "PR 9123 slow stream",
        "base_url": f"http://127.0.0.1:{stream_port}/v1",
        "models": [MODEL_ID],
        "available_models": [MODEL_ID],
    }, token=token)
    return created["id"]


def init_script(access_token: str, refresh_token: str, provider_id: str) -> str:
    checkpoint = f"external::{provider_id}::{urllib.parse.quote(MODEL_ID, safe='')}"
    seed = {
        "unsloth_auth_token": access_token,
        "unsloth_refresh_token": refresh_token,
        "unsloth_chat_connections_enabled": "true",
        "unsloth_chat_last_external_checkpoint": checkpoint,
        # tool calling would preflight against an endpoint that only streams plain text
        "unsloth_chat_tools_enabled": "false",
        "unsloth_chat_code_tools_enabled": "false",
        "unsloth_chat_image_tools_enabled": "false",
        "unsloth_chat_web_fetch_tools_enabled": "false",
        "unsloth_chat_deep_research_enabled": "false",
        "unsloth_chat_mcp_enabled": "false",
        "unsloth_chat_auto_title": "false",
    }
    return ("(() => { const seed = " + json.dumps(seed) + ";"
            " for (const k of Object.keys(seed)) {"
            " try { window.localStorage.setItem(k, seed[k]); } catch (e) {} } })();")


async def action_labels(page) -> list[str]:
    buttons = page.locator("form:has(textarea) .aui-composer-action-wrapper button")
    labels: list[str] = []
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        if await button.is_visible():
            labels.append((await button.get_attribute("aria-label")) or "")
    return labels


async def streamed_tokens(page) -> int:
    message = page.locator('[data-role="assistant"], .aui-assistant-message').last
    try:
        return (await message.inner_text(timeout=10_000)).count("token ")
    except Exception:  # noqa: BLE001 -- no assistant bubble yet is zero progress
        return 0


async def probe(base_url: str, access_token: str, refresh_token: str, provider_id: str,
                browser_name: str, artifact_dir: Path) -> None:
    async with open_chat(base_url,
                         init_scripts=[init_script(access_token, refresh_token, provider_id)],
                         viewport=(1100, 660), headless=True,
                         browser_name=browser_name) as sp:
        page = sp.page
        await page.goto(f"{base_url}/chat", wait_until="domcontentloaded")
        composer = page.locator("form:has(textarea) textarea").first
        await composer.wait_for(state="visible", timeout=90_000)
        await page.wait_for_timeout(6_000)

        await composer.click()
        await composer.fill("Count slowly for me.")
        await composer.press("Enter")

        running = page.locator(
            'form:has(textarea) .aui-composer-action-wrapper button[aria-label="Stop generating"], '
            'form:has(textarea) .aui-composer-action-wrapper button[aria-label="Queue message"]'
        )
        await running.first.wait_for(state="visible", timeout=180_000)
        if await page.locator('form:has(textarea) button[aria-label="Send message"]').count():
            fail("the composer still shows Send after the reply started; the thread never "
                 "entered its running state and there is nothing to assert on")

        idle_labels = await action_labels(page)
        print(f"running actions, empty composer: {idle_labels}", flush=True)
        if "Stop generating" not in idle_labels:
            fail("Stop generating is missing even with an empty composer; the running "
                 "composer is not in the state this probe assumes")
        pass_log("running composer offers Stop generating before any text is typed")

        await composer.click()
        await composer.fill(QUEUED_TEXT)
        await page.wait_for_timeout(2_000)
        typed = await composer.input_value()
        if typed.strip() != QUEUED_TEXT:
            fail(f"composer holds {typed!r}, not the queueable text; the typing missed")

        first = await streamed_tokens(page)
        await page.wait_for_timeout(2_000)
        second = await streamed_tokens(page)
        print(f"streamed tokens: {first} -> {second}", flush=True)
        if second <= first:
            fail(f"the reply stopped growing ({first} -> {second} tokens); the composer "
                 "state under test is not the running one")

        labels = await action_labels(page)
        print(f"running actions, typed composer: {labels}", flush=True)

        artifact_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(artifact_dir / f"composer-running-{browser_name}.png"),
                              clip={"x": 281, "y": 0, "width": 819, "height": 660})
        await page.locator("form:has(textarea)").first.screenshot(
            path=str(artifact_dir / f"composer-row-{browser_name}.png"))
        (artifact_dir / f"actions-{browser_name}.json").write_text(json.dumps({
            "empty_composer": idle_labels,
            "typed_composer": labels,
            "streamed_tokens": [first, second],
        }, indent=2))

        if "Queue message" not in labels:
            fail("Queue message is missing while queueable text sits in the running "
                 f"composer; actions were {labels}")
        if "Stop generating" not in labels:
            fail("Stop generating disappeared once text was typed into the running "
                 f"composer; actions were {labels}. This is issue 9089")
        pass_log("Stop generating and Queue message are both offered while the reply "
                 "streams and the composer holds queueable text")


async def main() -> None:
    home = Path(os.environ["UNSLOTH_STUDIO_HOME"]).resolve()
    browser_name = os.environ.get("STUDIO_BROWSER", "chromium")
    artifact_dir = Path(os.environ.get("STUDIO_ARTIFACT_DIR", "studio-live-artifacts")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = start_studio(home, artifact_dir / "studio.log", port)
    server, stream_port = start_stream_server()
    try:
        wait_for_health(base_url)
        pass_log(f"Studio healthy on {base_url}")
        access_token, refresh_token = authenticate(base_url, home)
        pass_log("authenticated against the install's own credential")
        provider_id = register_provider(base_url, access_token, stream_port)
        pass_log("registered the loopback streaming provider")
        await probe(base_url, access_token, refresh_token, provider_id,
                    browser_name, artifact_dir)
    finally:
        server.shutdown()
        server.server_close()
        stop_process(proc)


if __name__ == "__main__":
    asyncio.run(main())

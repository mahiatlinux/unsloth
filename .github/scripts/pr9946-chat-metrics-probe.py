#!/usr/bin/env python3
"""Generated live Unsloth Studio scenario probe.

Do not print provider keys, bootstrap passwords, auth tokens, or API keys.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx
from studio_test_kit.auth import (
    anthropic_provider,
    gemini_provider,
    login,
    openai_provider,
    seed_init_script,
)
from studio_test_kit.compose import hstack_images, hstack_videos
from studio_test_kit.flows import image_generation, multi_turn_chat, tool_pills, vision_upload
from studio_test_kit.ui import open_chat, send_prompt, wait_for_stream

SCENARIO = "local-chat"
PROVIDER = "gemini"
MODEL = "gemini-2.5-flash"
PROMPT = "List the integers from 1 through 120, one per line."
TURNS = ["Translate 'good morning' into Japanese.", "Now answer in a pirate voice.", "Summarize this thread in 5 words."]
RECORD_VIDEO = True
LOCAL_MODEL = "unsloth/Qwen3-1.7B-GGUF"
LOCAL_GGUF_VARIANT = "UD-Q4_K_XL"
LOCAL_MAX_SEQ_LENGTH = 4096
LOCAL_PARALLEL = 2
PRE_REF = "main"
INSTALL_UNIX = "bash ./install.sh --local --no-torch"
INSTALL_WINDOWS = "& ./install.ps1 --local --no-torch"


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
    candidates.extend(home.glob(".venv*/Scripts/unsloth.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    fail(f"could not find unsloth CLI under {home}")


def read_bootstrap_password(home: Path, log_path: Path) -> str | None:
    for rel in ("auth/.bootstrap_password", ".bootstrap_password"):
        path = home / rel
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(
        r"(?i)(?:bootstrap|initial|generated)\s*password(?:\s+is)?\s*[:=]?\s+(\S+)",
        log_text,
    )
    return match.group(1).strip().strip(".,") if match else None


def read_api_key(log_path: Path, timeout_s: int = 900) -> str:
    deadline = time.time() + timeout_s
    pattern = re.compile(r"API Key:\s+(sk-unsloth-[a-f0-9]+)")
    while time.time() < deadline:
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        match = pattern.search(text)
        if match:
            return match.group(1)
        time.sleep(2)
    fail("timed out waiting for Studio run API key in log")


def wait_for_health(base_url: str, timeout_s: int = 180) -> str:
    deadline = time.time() + timeout_s
    paths = ("/healthz", "/api/health", "/")
    while time.time() < deadline:
        for path in paths:
            try:
                with urllib.request.urlopen(f"{base_url}{path}", timeout=3) as resp:
                    if resp.status < 500:
                        return path
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
        time.sleep(2)
    fail(f"Studio did not become healthy within {timeout_s}s; tried {paths}")


def process_kwargs(log_path: Path, env: dict[str, str]) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    kwargs: dict = {"stdout": log_handle, "stderr": subprocess.STDOUT, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    kwargs["_log_handle"] = log_handle
    return kwargs


def start_process(cmd: list[str], log_path: Path, env: dict[str, str]) -> subprocess.Popen:
    kwargs = process_kwargs(log_path, env)
    log_handle = kwargs.pop("_log_handle")
    print("Launching: " + " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, **kwargs)
    log_handle.close()
    return proc


def studio_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["UNSLOTH_STUDIO_HOME"] = str(home)
    env.pop("STUDIO_HOME", None)
    return env


def start_plain_studio(home: Path, log_path: Path, port: int) -> subprocess.Popen:
    return start_process(
        [str(find_unsloth_bin(home)), "studio", "-H", "127.0.0.1", "-p", str(port)],
        log_path,
        studio_env(home),
    )


def start_local_studio_run(home: Path, log_path: Path, port: int) -> subprocess.Popen:
    cmd = [
        str(find_unsloth_bin(home)),
        "studio",
        "run",
        "--model",
        LOCAL_MODEL,
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
        "--api-key-name",
        "ci",
        "--max-seq-length",
        str(LOCAL_MAX_SEQ_LENGTH),
        "--parallel",
        str(LOCAL_PARALLEL),
        "--disable-tools",
    ]
    if LOCAL_GGUF_VARIANT:
        cmd.extend(["--gguf-variant", LOCAL_GGUF_VARIANT])
    return start_process(cmd, log_path, studio_env(home))


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        proc.terminate()
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()


def provider_seed(model: str):
    if PROVIDER == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            fail("GEMINI_API_KEY secret is required for provider scenario")
        return gemini_provider(api_key=key, models=[model])
    if PROVIDER == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            fail("OPENAI_API_KEY secret is required for provider scenario")
        return openai_provider(api_key=key, models=[model])
    if PROVIDER == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            fail("ANTHROPIC_API_KEY secret is required for provider scenario")
        return anthropic_provider(api_key=key, models=[model])
    fail(f"unsupported provider: {PROVIDER}")


def video_dir(artifact_dir: Path, name: str) -> Path | None:
    return artifact_dir / "video" / name if RECORD_VIDEO else None


async def browser_request(page, path: str, *, method: str = "GET", body=None, authorize: bool = True):
    return await page.evaluate(
        """async ({path, method, body, authorize}) => {
            const headers = {};
            if (authorize) {
                headers.Authorization = `Bearer ${localStorage.getItem("unsloth_auth_token")}`;
            }
            if (body !== null) headers["Content-Type"] = "application/json";
            const response = await fetch(path, {
                method,
                headers,
                body: body === null ? undefined : JSON.stringify(body),
            });
            const text = await response.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch (_) {}
            return {
                status: response.status,
                headers: Object.fromEntries(response.headers.entries()),
                text,
                body: parsed,
            };
        }""",
        {"path": path, "method": method, "body": body, "authorize": authorize},
    )


async def wait_until(check, *, timeout_s: float = 30, interval_s: float = 0.2, message: str):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            last = await check()
            if last:
                return last
        except Exception as exc:
            last = exc
        await asyncio.sleep(interval_s)
    fail(f"{message}; last={last!r}")


def run_id_from_events_url(url: str) -> str | None:
    match = re.search(r"/api/inference/chat-runs/([^/?]+)/events", url)
    return match.group(1) if match else None


async def auth_init(base_url: str, password: str, providers: list | None = None) -> str:
    auth = await login(base_url, "unsloth", password)
    pass_log("Studio API login succeeded")
    if auth.must_change_password:
        new_password = os.environ.get("STUDIO_TEST_PASSWORD", "UnslothStudioCI2026!")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{base_url}/api/auth/change-password",
                headers={"Authorization": f"Bearer {auth.access_token}"},
                json={"current_password": password, "new_password": new_password},
            )
            response.raise_for_status()
            body = response.json()
        auth.access_token = body["access_token"]
        auth.refresh_token = body.get("refresh_token", "")
        pass_log("Studio first-boot password change completed")
    return seed_init_script(auth, providers or [])


async def scenario_smoke(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init = await auth_init(base_url, password)
    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "smoke"),
        video_name=f"smoke-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        composer = sp.page.locator("form:has(textarea) textarea").first
        await composer.wait_for(state="visible", timeout=30_000)
        await sp.screenshot(artifact_dir / f"studio-chat-{browser_name}.png")
    pass_log(f"Playwright {browser_name} opened /chat and found the composer")


async def scenario_provider_chat(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init = await auth_init(base_url, password, [provider_seed(MODEL)])
    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "provider-chat"),
        video_name=f"provider-chat-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        result = await multi_turn_chat(sp, MODEL, TURNS, artifact_dir / "provider-chat")
    result.attach_video(sp)
    pass_log(f"provider chat completed {result.artefacts.get('turn_count', len(TURNS))} turns")


async def scenario_image_gen(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init = await auth_init(base_url, password, [provider_seed(MODEL)])
    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "image-gen"),
        video_name=f"image-gen-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        result = await image_generation(sp, MODEL, PROMPT, artifact_dir / "image-gen")
    result.attach_video(sp)
    pass_log(f"image generation saved {result.artefacts.get('image_bytes')} bytes")


async def scenario_tools_pills(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init = await auth_init(base_url, password, [provider_seed(MODEL)])
    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "tools-pills"),
        video_name=f"tools-pills-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        result = await tool_pills(sp, MODEL, artifact_dir / "tools-pills")
    result.attach_video(sp)
    pass_log("Search and Code composer pill flow completed")


def write_default_vision_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tiny_png = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "AAIAAAoAAv/lxKUAAAAASUVORK5CYII="
    )
    path.write_bytes(base64.b64decode(tiny_png))
    return path


async def scenario_vision_upload(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    image_path = Path(os.environ.get("STUDIO_VISION_IMAGE", ""))
    if not image_path.is_file():
        image_path = write_default_vision_image(artifact_dir / "vision" / "input.png")
    init = await auth_init(base_url, password, [provider_seed(MODEL)])
    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "vision-upload"),
        video_name=f"vision-upload-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        result = await vision_upload(sp, MODEL, image_path, PROMPT, artifact_dir / "vision-upload")
    result.attach_video(sp)
    pass_log("vision upload flow completed")


async def scenario_local_chat(base_url: str, api_key: str, browser_name: str, artifact_dir: Path, password: str | None) -> None:
    payload = {
        "model": LOCAL_MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "max_tokens": 64,
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        streaming_payload = {
            **payload,
            "stream": True,
            "max_tokens": 16,
        }
        streaming_response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=streaming_payload,
        )
        streaming_response.raise_for_status()
        direct_monitor_id = streaming_response.headers.get("X-Unsloth-Monitor-Id")
        if not direct_monitor_id:
            fail("streaming chat response omitted X-Unsloth-Monitor-Id")
        if "data:" not in streaming_response.text or "[DONE]" not in streaming_response.text:
            fail("streaming chat response body was not valid SSE")
        if direct_monitor_id in streaming_response.text:
            fail("monitor id leaked into the streaming chat body")
        health = await client.get(f"{base_url}/healthz")
        if "X-Unsloth-Monitor-Id" in health.headers:
            fail("non-chat health response exposed a monitor id")
    (artifact_dir / "local-chat-response.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    message = (body.get("choices") or [{}])[0].get("message") or {}
    content = (message.get("content") or message.get("reasoning_content") or "").strip()
    if not content:
        fail("local-chat API returned no assistant content")
    pass_log("direct real-model chat returned content and an isolated monitor header")

    init_scripts = [await auth_init(base_url, password)] if password else []
    if not init_scripts:
        fail("Studio UI bootstrap password was unavailable")

    async with open_chat(
        base_url,
        init_scripts=init_scripts,
        video_dir=video_dir(artifact_dir, "local-chat"),
        video_name=f"local-chat-{browser_name}",
        transcode_mp4=False,
        browser_name=browser_name,
    ) as sp:
        page = sp.page
        event_responses: list[dict] = []
        monitor_samples: list[dict] = []

        async def capture_response(response):
            url = response.url
            if "/api/inference/chat-runs/" in url and "/events" in url:
                headers = await response.all_headers()
                event_responses.append(
                    {
                        "url": url,
                        "run_id": run_id_from_events_url(url),
                        "monitor_id": headers.get("x-unsloth-monitor-id"),
                    }
                )
            elif "/api/inference/monitor/" in url:
                try:
                    data = await response.json()
                except Exception:
                    data = None
                monitor_samples.append(
                    {
                        "url": url,
                        "status": response.status,
                        "body": data,
                    }
                )

        page.on("response", capture_response)
        tps = page.locator('div[role="status"][aria-label^="Live generation speed"]').first
        await tps.wait_for(state="visible", timeout=30_000)

        async def tps_unavailable():
            return (await tps.get_attribute("aria-label")) == "Live generation speed unavailable"

        async def current_thread_id():
            match = re.search(r"/chat/([^/?#]+)", page.url)
            if match:
                return match.group(1)
            result = await browser_request(page, "/api/chat/threads?includeArchived=true")
            if result["status"] != 200:
                return None
            threads = result["body"].get("threads") or []
            if not threads:
                return None
            threads.sort(
                key=lambda thread: thread.get("updatedAt") or thread.get("createdAt") or 0,
                reverse=True,
            )
            return threads[0].get("id")

        async def wait_for_monitor(after: int, *, timeout_s: float = 45):
            async def find_monitor():
                for item in reversed(event_responses[after:]):
                    if item["monitor_id"]:
                        return item
                return None

            return await wait_until(
                find_monitor,
                timeout_s=timeout_s,
                message="durable event response never exposed its monitor id",
            )

        async def wait_for_run_response(after: int, *, timeout_s: float = 30):
            async def find_run():
                for item in reversed(event_responses[after:]):
                    if item["run_id"]:
                        return item
                return None

            return await wait_until(
                find_run,
                timeout_s=timeout_s,
                message="durable event response was never observed",
            )

        async def wait_for_live_monitor(monitor_id: str, *, timeout_s: float = 60):
            async def matches_exact_poll():
                label = await tps.get_attribute("aria-label") or ""
                match = re.search(r"([0-9]+(?:\.[0-9]+)?) tokens per second", label)
                if not match:
                    return None
                displayed = float(match.group(1))
                for sample in reversed(monitor_samples):
                    if not sample["url"].endswith(f"/monitor/{monitor_id}"):
                        continue
                    data = sample["body"]
                    if not isinstance(data, dict) or data.get("status") != "running":
                        continue
                    rate = data.get("tok_per_sec")
                    if isinstance(rate, (int, float)) and round(float(rate), 1) == displayed:
                        return {"displayed": displayed, "sample": data}
                return None

            return await wait_until(
                matches_exact_poll,
                timeout_s=timeout_s,
                message=f"TPS never matched the browser poll for monitor {monitor_id}",
            )

        async def sidebar_usage_text(thread_id: str):
            row = page.locator(
                f'[data-testid="recent-thread"][data-thread-id="{thread_id}"]'
            ).first
            await row.wait_for(state="attached", timeout=30_000)
            metric = row.get_by_test_id("sidebar-last-request-usage")
            await metric.wait_for(state="attached", timeout=30_000)
            return (await metric.inner_text()).strip()

        async def newest_saved_usage(thread_id: str):
            result = await browser_request(page, f"/api/chat/threads/{thread_id}/messages")
            if result["status"] != 200:
                fail(f"message read for {thread_id} returned {result['status']}")
            messages = result["body"]["messages"]
            assistants = [message for message in messages if message.get("role") == "assistant"]
            if not assistants:
                return None
            return (assistants[-1].get("metadata") or {}).get("contextUsage")

        async def assert_sidebar_matches_saved(thread_id: str):
            usage = await newest_saved_usage(thread_id)
            if not isinstance(usage, dict) or not isinstance(usage.get("totalTokens"), (int, float)):
                fail(f"newest assistant for {thread_id} has no saved contextUsage: {usage!r}")
            text = await wait_until(
                lambda: sidebar_usage_text(thread_id),
                timeout_s=30,
                message=f"sidebar usage missing for {thread_id}",
            )
            shown = int("".join(re.findall(r"\d", text)))
            expected = int(usage["totalTokens"])
            if shown != expected:
                fail(f"sidebar showed {shown} tokens but newest saved assistant has {expected}")
            return expected

        await wait_until(tps_unavailable, timeout_s=15, message="initial TPS was not unavailable")
        await sp.screenshot(artifact_dir / "01-unavailable.png")

        first_event_index = len(event_responses)
        first_assistant_count = await page.locator('[data-role="assistant"]').count()
        await send_prompt(sp, "Reply with exactly: normal-generation-ok")
        await wait_for_stream(sp, timeout_ms=180_000)
        await page.wait_for_function(
            "want => document.querySelectorAll('[data-role=\"assistant\"]').length > want",
            arg=first_assistant_count,
            timeout=30_000,
        )
        first_thread = await wait_until(
            current_thread_id,
            timeout_s=30,
            message="normal generation did not persist a thread id",
        )
        first_event = await wait_for_run_response(first_event_index)
        await wait_until(tps_unavailable, timeout_s=15, message="completed generation retained TPS")
        first_total = await assert_sidebar_matches_saved(first_thread)
        await sp.screenshot(artifact_dir / "02-completed-sidebar.png")
        pass_log(f"normal generation saved and rendered its exact {first_total}-token request total")

        active_event_index = len(event_responses)
        await send_prompt(sp, "Count from 1 to 500, one integer per line. Do not stop early.")
        active_monitor = await wait_for_monitor(active_event_index)
        active_id = active_monitor["monitor_id"]
        await wait_for_live_monitor(active_id)

        async def old_sidebar_cleared():
            return (await sidebar_usage_text(first_thread)).endswith("—")

        await wait_until(
            old_sidebar_cleared,
            timeout_s=30,
            message="a new partial assistant silently retained the older sidebar total",
        )
        await sp.screenshot(artifact_dir / "03-active-tps-sidebar-cleared.png")

        async def transient_monitor_failure(route):
            await route.fulfill(status=503, content_type="application/json", body='{"detail":"temporary"}')

        await page.route("**/api/inference/monitor/**", transient_monitor_failure)
        await wait_until(tps_unavailable, timeout_s=15, message="monitor fetch failure retained stale TPS")
        await sp.screenshot(artifact_dir / "04-monitor-unavailable.png")
        await page.unroute("**/api/inference/monitor/**", transient_monitor_failure)
        await wait_for_live_monitor(active_id, timeout_s=30)
        stop = page.locator('button[aria-label="Stop generating"]').first
        await stop.click(timeout=10_000)
        await stop.wait_for(state="hidden", timeout=30_000)
        await wait_until(tps_unavailable, timeout_s=15, message="cancelled generation retained TPS")
        await sp.screenshot(artifact_dir / "05-cancelled.png")
        pass_log("transient monitor failure recovered and cancellation cleared request-owned TPS")

        stale_event_index = len(event_responses)
        await send_prompt(sp, "Count from 1 to 400, one integer per line. Do not stop early.")
        stale_monitor = await wait_for_monitor(stale_event_index)
        stale_id = stale_monitor["monitor_id"]

        async def stale_monitor_route(route):
            await route.fulfill(status=404, content_type="application/json", body='{"detail":"missing"}')

        stale_pattern = f"**/api/inference/monitor/{stale_id}"
        await page.route(stale_pattern, stale_monitor_route)
        await wait_until(tps_unavailable, timeout_s=15, message="stale monitor id retained TPS")
        await sp.screenshot(artifact_dir / "06-stale-monitor.png")
        await page.unroute(stale_pattern, stale_monitor_route)
        if await stop.is_visible():
            await stop.click()
            await stop.wait_for(state="hidden", timeout=30_000)

        replacement_event_index = len(event_responses)
        await send_prompt(sp, "Count from 1 to 220, one integer per line. Do not stop early.")
        replacement_monitor = await wait_for_monitor(replacement_event_index)
        replacement_id = replacement_monitor["monitor_id"]
        if replacement_id in {active_id, stale_id}:
            fail("replacement generation reused an older monitor id")
        await wait_for_live_monitor(replacement_id)
        await wait_for_stream(sp, timeout_ms=180_000)
        await wait_until(tps_unavailable, timeout_s=15, message="replacement completion retained TPS")
        await assert_sidebar_matches_saved(first_thread)
        pass_log("stale monitor terminalized only its owner and the replacement request recovered")

        resume_event_index = len(event_responses)
        await send_prompt(sp, "Count from 1 to 900, one integer per line. Do not stop early.")
        resume_monitor = await wait_for_monitor(resume_event_index)
        resume_id = resume_monitor["monitor_id"]
        await wait_for_live_monitor(resume_id)
        await page.reload(wait_until="domcontentloaded")
        await page.locator("form:has(textarea) textarea").first.wait_for(state="visible", timeout=30_000)
        await page.locator(
            f'[data-testid="recent-thread"][data-thread-id="{first_thread}"]'
        ).first.click(timeout=30_000)
        await wait_for_live_monitor(resume_id, timeout_s=60)
        await sp.screenshot(artifact_dir / "07-reconnected-active.png")

        new_chat = page.get_by_role("button", name=re.compile(r"^New Chat$", re.I)).first
        await new_chat.click(timeout=15_000)
        await wait_until(tps_unavailable, timeout_s=15, message="TPS leaked after switching to a blank thread")
        await sp.screenshot(artifact_dir / "08-thread-switched-unavailable.png")

        concurrent_event_index = len(event_responses)
        await send_prompt(sp, "Count backwards from 700 to 1, one integer per line. Do not stop early.")
        concurrent_monitor = await wait_for_monitor(concurrent_event_index)
        concurrent_id = concurrent_monitor["monitor_id"]
        if concurrent_id == resume_id:
            fail("concurrent thread received the first thread's monitor id")
        concurrent_thread = await wait_until(
            current_thread_id,
            timeout_s=30,
            message="concurrent generation did not persist its thread",
        )
        await wait_for_live_monitor(concurrent_id)
        await sp.screenshot(artifact_dir / "09-concurrent-active.png")

        first_row = page.locator(
            f'[data-testid="recent-thread"][data-thread-id="{first_thread}"]'
        ).first
        await first_row.click()
        await wait_for_live_monitor(resume_id, timeout_s=20)
        await sp.screenshot(artifact_dir / "10-first-thread-active.png")
        concurrent_row = page.locator(
            f'[data-testid="recent-thread"][data-thread-id="{concurrent_thread}"]'
        ).first
        await concurrent_row.click()
        await wait_for_live_monitor(concurrent_id, timeout_s=20)
        if await stop.is_visible():
            await stop.click()
            await stop.wait_for(state="hidden", timeout=30_000)
        await wait_until(tps_unavailable, timeout_s=15, message="concurrent cancellation retained TPS")
        await first_row.click()
        if await stop.is_visible():
            await stop.click()
            await stop.wait_for(state="hidden", timeout=30_000)
        await wait_until(tps_unavailable, timeout_s=15, message="first concurrent request retained TPS")
        pass_log("reconnect, concurrent chats, and thread switching kept monitor ownership isolated")

        for cycle in range(3):
            cycle_index = len(event_responses)
            await send_prompt(sp, f"Count from 1 to 300, one per line. Cycle {cycle}.")
            cycle_monitor = await wait_for_monitor(cycle_index)
            await wait_for_live_monitor(cycle_monitor["monitor_id"], timeout_s=45)
            await stop.click(timeout=10_000)
            await stop.wait_for(state="hidden", timeout=30_000)
            await wait_until(tps_unavailable, timeout_s=15, message=f"rapid stop {cycle} retained TPS")
        pass_log("three rapid start/stop cycles left no TPS behind")

        long_prompt = ("alpha beta gamma delta " * 420) + " Reply with exactly: long-context-ok"
        long_index = len(event_responses)
        await send_prompt(sp, long_prompt)
        await wait_for_monitor(long_index)
        await wait_for_stream(sp, timeout_ms=240_000)
        long_total = await assert_sidebar_matches_saved(first_thread)
        if long_total < 1000:
            fail(f"long-context saved usage was unexpectedly small: {long_total}")
        await sp.screenshot(artifact_dir / "11-long-context-completed.png")

        failed_index = len(event_responses)
        overflow_prompt = ("overflow " * 7000) + " Reply with exactly: should-not-run"
        await send_prompt(sp, overflow_prompt)
        failed_event = await wait_for_run_response(failed_index)
        failed_run_id = failed_event["run_id"]

        async def failed_snapshot():
            result = await browser_request(page, f"/api/inference/chat-runs/{failed_run_id}")
            if result["status"] == 200 and result["body"].get("status") in {"failed", "cancelled"}:
                return result["body"]
            return None

        failed_run = await wait_until(
            failed_snapshot,
            timeout_s=90,
            message="overflow generation did not reach a failed terminal state",
        )
        await wait_until(tps_unavailable, timeout_s=15, message="failed generation retained TPS")
        if not (await sidebar_usage_text(first_thread)).endswith("—"):
            fail("failed newest assistant fell back to an older sidebar total")
        await sp.screenshot(artifact_dir / "12-failed.png")
        if "monitor" in json.dumps(failed_run).lower():
            fail("durable persisted run schema contains monitor correlation data")

        events_replay = await browser_request(
            page,
            f"/api/inference/chat-runs/{first_event['run_id']}/events?after=0",
            method="POST",
        )
        if events_replay["status"] != 200 or "event: chunk" not in events_replay["text"]:
            fail("durable SSE replay no longer contains valid chunk events")
        if "x-unsloth-monitor-id" in events_replay["text"].lower():
            fail("monitor response header leaked into the SSE body")
        no_auth_monitor = await browser_request(
            page,
            f"/api/inference/monitor/{active_id}",
            authorize=False,
        )
        no_auth_events = await browser_request(
            page,
            f"/api/inference/chat-runs/{first_event['run_id']}/events?after=0",
            method="POST",
            authorize=False,
        )
        if no_auth_monitor["status"] != 401 or no_auth_events["status"] != 401:
            fail("monitor or durable events bypassed authentication")

        now = int(time.time() * 1000)
        fixture_prefix = f"metrics-{now}"

        async def save_thread(suffix: str, title: str, messages: list[dict], *, pair_id=None):
            thread_id = f"{fixture_prefix}-{suffix}"
            thread = {
                "id": thread_id,
                "title": title,
                "modelType": "base",
                "modelId": LOCAL_MODEL,
                "modelGgufVariant": LOCAL_GGUF_VARIANT,
                "pairId": pair_id,
                "createdAt": now,
                "updatedAt": now,
            }
            saved = await browser_request(page, "/api/chat/threads", method="POST", body=thread)
            if saved["status"] != 200:
                fail(f"fixture thread {suffix} failed: {saved}")
            if messages:
                synced = await browser_request(
                    page,
                    f"/api/chat/threads/{thread_id}/messages",
                    method="PUT",
                    body={"messages": messages, "pruneMissing": True, "deletedMessageIds": []},
                )
                if synced["status"] != 200:
                    fail(f"fixture messages {suffix} failed: {synced}")
            return thread_id

        def message(thread_id: str, suffix: str, role: str, created: int, metadata=None):
            value = {
                "id": f"{thread_id}-{suffix}",
                "threadId": thread_id,
                "role": role,
                "content": [{"type": "text", "text": suffix}],
                "createdAt": created,
            }
            if metadata is not None:
                value["metadata"] = metadata
            return value

        def usage(total: int):
            return {
                "contextUsage": {
                    "promptTokens": total - 10,
                    "completionTokens": 10,
                    "totalTokens": total,
                }
            }

        empty_id = await save_thread("empty", "Metric empty chat", [])
        user_id = f"{fixture_prefix}-user"
        user_id = await save_thread(
            "user",
            "Metric user only",
            [message(user_id, "u", "user", now, None)],
        )
        legacy_id = f"{fixture_prefix}-legacy"
        legacy_id = await save_thread(
            "legacy",
            "Metric legacy assistant",
            [message(legacy_id, "a", "assistant", now, None)],
        )
        partial_id = f"{fixture_prefix}-partial"
        partial_id = await save_thread(
            "partial",
            "Metric partial metadata",
            [message(partial_id, "a", "assistant", now, {"contextUsage": {"promptTokens": 5, "totalTokens": 7}})],
        )
        malformed_id = f"{fixture_prefix}-malformed"
        malformed_id = await save_thread(
            "malformed",
            "Metric malformed newest",
            [
                message(malformed_id, "old", "assistant", now, usage(111)),
                message(malformed_id, "new", "assistant", now + 1, {"contextUsage": "bad"}),
            ],
        )
        multiple_id = f"{fixture_prefix}-multiple"
        multiple_id = await save_thread(
            "multiple",
            "Metric newest valid",
            [
                message(multiple_id, "old", "assistant", now, usage(111)),
                message(multiple_id, "new", "assistant", now + 1, usage(222)),
            ],
        )
        pair_id = f"{fixture_prefix}-pair"
        compare_a = f"{fixture_prefix}-compare-a"
        compare_b = f"{fixture_prefix}-compare-b"
        await save_thread(
            "compare-a",
            "Metric compare row",
            [message(compare_a, "a", "assistant", now, usage(333))],
            pair_id=pair_id,
        )
        await save_thread(
            "compare-b",
            "Metric compare row",
            [message(compare_b, "a", "assistant", now, usage(444))],
            pair_id=pair_id,
        )
        deleted_id = f"{fixture_prefix}-deleted"
        deleted_id = await save_thread(
            "deleted",
            "Metric deleted row",
            [message(deleted_id, "a", "assistant", now, usage(555))],
        )
        deleted = await browser_request(
            page,
            "/api/chat/threads",
            method="DELETE",
            body={"ids": [deleted_id], "delete_files": False},
        )
        if deleted["status"] != 200:
            fail(f"fixture delete failed: {deleted}")

        await page.reload(wait_until="domcontentloaded")
        await page.locator("form:has(textarea) textarea").first.wait_for(state="visible", timeout=30_000)
        for thread_id in (empty_id, user_id, legacy_id, partial_id, malformed_id):
            text = await sidebar_usage_text(thread_id)
            if not text.endswith("—"):
                fail(f"{thread_id} fell back to aggregated or older usage: {text!r}")
        multiple_text = await sidebar_usage_text(multiple_id)
        if int("".join(re.findall(r"\d", multiple_text))) != 222:
            fail(f"multiple assistants did not use only the newest valid request: {multiple_text!r}")
        compare_row = page.locator(f'[data-testid="recent-thread"][data-thread-id="{pair_id}"]').first
        await compare_row.wait_for(state="attached", timeout=30_000)
        if await compare_row.get_by_test_id("sidebar-last-request-usage").count():
            fail("compare row rendered a single-request usage metric")
        if await page.locator(f'[data-testid="recent-thread"][data-thread-id="{deleted_id}"]').count():
            fail("deleted chat reappeared after reload")
        await sp.screenshot(artifact_dir / "13-sidebar-edge-cases.png")
        await page.reload(wait_until="domcontentloaded")
        if int("".join(re.findall(r"\d", await sidebar_usage_text(multiple_id)))) != 222:
            fail("reloaded chat lost its newest saved assistant usage")

        summaries = await browser_request(page, "/api/chat/threads/sidebar-summaries?includeArchived=true")
        if summaries["status"] != 200:
            fail("sidebar summary endpoint failed in the rendered flow")
        history = await browser_request(page, "/api/chat/threads?includeArchived=true")
        if "x-unsloth-monitor-id" in history["headers"]:
            fail("chat history response unexpectedly carried a monitor id")
        (artifact_dir / "captured-event-headers.json").write_text(
            json.dumps(event_responses, indent=2), encoding="utf-8"
        )
        (artifact_dir / "captured-monitor-samples.json").write_text(
            json.dumps(monitor_samples, indent=2), encoding="utf-8"
        )
        pass_log("sidebar edge cases, SSE body, persisted schema, and auth boundaries passed")

    pass_log("real-model Playwright chat-metrics lifecycle completed")


def install_pre_ref(root: Path, log_path: Path) -> Path:
    if os.name == "nt":
        fail("side-by-side scenario is currently intended for Unix runners")
    repo = root / "pre-repo"
    home = root / "pre-home"
    origin = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
    clone_cmd = ["git", "clone", "--depth", "1", "--branch", PRE_REF, origin, str(repo)]
    try:
        subprocess.run(clone_cmd, check=True)
    except subprocess.CalledProcessError:
        warn(f"direct clone of pre-ref {PRE_REF!r} failed; trying fetch checkout fallback")
        if repo.exists():
            shutil.rmtree(repo)
        subprocess.run(["git", "clone", "--no-local", ".", str(repo)], check=True)
        subprocess.run(["git", "fetch", origin, PRE_REF, "--depth", "1"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=repo, check=True)
    home.mkdir(parents=True, exist_ok=True)
    env = studio_env(home)
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(INSTALL_UNIX, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=2700, shell=True)
    return home


async def scenario_side_by_side(post_home: Path, post_base: str, post_password: str, browser_name: str, artifact_dir: Path) -> None:
    root = artifact_dir / "side-by-side"
    pre_home = install_pre_ref(root, artifact_dir / "pre-install.log")
    pre_port = free_port()
    pre_base = f"http://127.0.0.1:{pre_port}"
    pre_proc = start_plain_studio(pre_home, artifact_dir / "pre-studio.log", pre_port)
    try:
        wait_for_health(pre_base, timeout_s=180)
        pre_password = read_bootstrap_password(pre_home, artifact_dir / "pre-studio.log")
        if not pre_password:
            fail("could not read pre-ref Studio bootstrap password")
        async def drive(label: str, base: str, password: str):
            init = await auth_init(base, password, [provider_seed(MODEL)])
            async with open_chat(
                base,
                init_scripts=[init],
                video_dir=video_dir(artifact_dir, label),
                video_name=f"{label}-{browser_name}",
                transcode_mp4=False,
                browser_name=browser_name,
            ) as sp:
                result = await multi_turn_chat(sp, MODEL, TURNS, artifact_dir / label)
            result.attach_video(sp)
            return result
        pre = await drive("pre", pre_base, pre_password)
        post = await drive("post", post_base, post_password)
        combined = artifact_dir / "combined"
        combined.mkdir(parents=True, exist_ok=True)
        for idx, (left, right) in enumerate(zip(pre.screenshots, post.screenshots), start=1):
            hstack_images(left, right, combined / f"sxs_{idx:02d}.png", label_left=PRE_REF, label_right="post")
        if pre.video_webm and post.video_webm:
            try:
                hstack_videos(pre.video_webm, post.video_webm, combined / "sxs.mp4")
            except Exception as exc:
                warn(f"side-by-side video composition skipped: {exc}")
        pass_log("side-by-side provider chat comparison completed")
    finally:
        stop_process(pre_proc)


async def run_plain_scenario(home: Path, base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    if SCENARIO == "smoke":
        await scenario_smoke(base_url, password, browser_name, artifact_dir)
    elif SCENARIO == "provider-chat":
        await scenario_provider_chat(base_url, password, browser_name, artifact_dir)
    elif SCENARIO == "image-gen":
        await scenario_image_gen(base_url, password, browser_name, artifact_dir)
    elif SCENARIO == "tools-pills":
        await scenario_tools_pills(base_url, password, browser_name, artifact_dir)
    elif SCENARIO == "vision-upload":
        await scenario_vision_upload(base_url, password, browser_name, artifact_dir)
    elif SCENARIO == "side-by-side":
        await scenario_side_by_side(home, base_url, password, browser_name, artifact_dir)
    else:
        fail(f"unexpected plain Studio scenario: {SCENARIO}")


async def main() -> None:
    home = Path(os.environ["UNSLOTH_STUDIO_HOME"]).resolve()
    browser_name = os.environ.get("STUDIO_BROWSER", "chromium")
    artifact_dir = Path(os.environ.get("STUDIO_ARTIFACT_DIR", "studio-live-artifacts")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc: subprocess.Popen | None = None
    try:
        if SCENARIO == "local-chat":
            log_path = artifact_dir / "studio-run.log"
            proc = start_local_studio_run(home, log_path, port)
            api_key = read_api_key(log_path)
            health_path = wait_for_health(base_url, timeout_s=900)
            pass_log(f"Studio run healthy at {health_path} on {base_url}")

            password = read_bootstrap_password(home, log_path)
            await scenario_local_chat(base_url, api_key, browser_name, artifact_dir, password)
        else:
            log_path = artifact_dir / "studio.log"
            proc = start_plain_studio(home, log_path, port)
            health_path = wait_for_health(base_url)
            pass_log(f"Studio healthy at {health_path} on {base_url}")
            password = read_bootstrap_password(home, log_path)
            if not password:
                fail("could not read Studio bootstrap password from install home or log")
            await run_plain_scenario(home, base_url, password, browser_name, artifact_dir)
    finally:
        stop_process(proc)


if __name__ == "__main__":
    asyncio.run(main())

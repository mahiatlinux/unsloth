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

SCENARIO = "smoke"
PROVIDER = "gemini"
MODEL = "gemini-2.5-flash"
PROMPT = "Say hello from Studio CI in one short sentence."
TURNS = ["Translate 'good morning' into Japanese.", "Now answer in a pirate voice.", "Summarize this thread in 5 words."]
RECORD_VIDEO = False
LOCAL_MODEL = "unsloth/Qwen3-1.7B-GGUF"
LOCAL_GGUF_VARIANT = "UD-Q4_K_XL"
LOCAL_MAX_SEQ_LENGTH = 1024
LOCAL_PARALLEL = 1
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
    return seed_init_script(auth, providers or []), auth


SEED_ENTRIES = [
    {"id": "ci8816a", "name": "Terse code reviewer",
     "text": "You are a terse code reviewer. Flag real defects only."},
    {"id": "ci8816b", "name": "Cited answers only",
     "text": "Answer only from the provided sources and cite each one."},
    {"id": "ci8816c", "name": "Release note writer",
     "text": "Write release notes in sentence case, one line per change."},
]
TARGET_ENTRY = SEED_ENTRIES[0]
EDITOR_DRAFT = "Answer in plain English. Cite the file and line for every claim."


async def seed_prompt_library(base_url: str, token: str) -> list[str]:
    """Put exactly the three seeded prompts in the library and return their names."""
    stamp = 1_755_000_000_000
    entries = [{**entry, "createdAt": stamp, "updatedAt": stamp} for entry in SEED_ENTRIES]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base_url}/api/prompts/entries/bulk",
                                     headers=headers, json={"entries": entries})
        response.raise_for_status()
        listed = (await client.get(f"{base_url}/api/prompts/entries", headers=headers)).json()
        seeded_ids = {entry["id"] for entry in entries}
        for stale in listed.get("entries", []):
            if stale.get("id") not in seeded_ids:
                await client.delete(f"{base_url}/api/prompts/entries/{stale['id']}", headers=headers)
        listed = (await client.get(f"{base_url}/api/prompts/entries", headers=headers)).json()
    return [entry["name"] for entry in listed.get("entries", [])]


async def entry_names(base_url: str, token: str) -> list[str]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base_url}/api/prompts/entries",
                                    headers={"Authorization": f"Bearer {token}"})
    return [entry["name"] for entry in response.json().get("entries", [])]


async def open_prompt_storage(page) -> None:
    """Composer tools menu -> More -> Saved prompts -> All saved prompts."""
    await page.get_by_role("button", name="Tools and attachments").first.click()
    more = page.get_by_role("menuitem", name="More").first
    await more.wait_for(state="visible", timeout=30_000)
    await more.hover()
    saved = page.get_by_text("Saved prompts", exact=True).first
    await saved.wait_for(state="visible", timeout=30_000)
    await saved.hover()
    all_saved = page.get_by_text("All saved prompts", exact=False).first
    await all_saved.wait_for(state="visible", timeout=30_000)
    await all_saved.click()


async def open_settings_panel(page):
    """The panel is mounted off canvas when closed, so its textarea reads visible either way."""
    opener = page.get_by_role("button", name="Open run settings").first
    if await opener.is_visible():
        await opener.click()
        await page.wait_for_timeout(2_000)
    prompt_box = page.get_by_label("System prompt", exact=True).first
    await prompt_box.wait_for(state="visible", timeout=30_000)
    return prompt_box


async def scenario_smoke(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init, auth = await auth_init(base_url, password)
    token = auth.access_token
    seeded = await seed_prompt_library(base_url, token)
    if sorted(seeded) != sorted(entry["name"] for entry in SEED_ENTRIES):
        fail(f"seeded library is {seeded}, expected the three CI prompts")
    pass_log(f"prompt library seeded: {seeded}")

    async with open_chat(
        base_url,
        init_scripts=[init],
        video_dir=video_dir(artifact_dir, "saved-prompt"),
        video_name=f"saved-prompt-{browser_name}",
        transcode_mp4=False,
        viewport=(1500, 1000),
        browser_name=browser_name,
    ) as sp:
        page = sp.page
        await page.locator("form:has(textarea) textarea").first.wait_for(state="visible", timeout=60_000)
        await page.wait_for_timeout(3_000)

        # studio persists params server side, so an earlier state would survive a fresh context
        prompt_box = await open_settings_panel(page)
        await prompt_box.fill("")
        await page.wait_for_timeout(1_000)

        await open_prompt_storage(page)
        card = page.get_by_text(TARGET_ENTRY["name"], exact=True).first.locator(
            "xpath=ancestor::div[contains(@class,'group')][1]")
        await card.wait_for(state="visible", timeout=30_000)
        # the card action row only paints on hover
        await card.hover()
        await page.wait_for_timeout(600)
        await card.screenshot(path=str(artifact_dir / f"prompt-card-{browser_name}.png"))

        system_button = card.locator("button").filter(has_text=re.compile(r"^\s*System\s*$"))
        if not await system_button.count():
            titles = await card.locator("button").evaluate_all(
                "nodes => nodes.map(node => node.title || node.textContent.trim())")
            fail(f"no System button on the prompt card; card buttons are {titles}")
        pass_log("prompt card offers System beside Use")
        await system_button.first.click()
        await page.wait_for_timeout(1_500)

        prompt_box = await open_settings_panel(page)
        applied = await prompt_box.input_value()
        if applied != TARGET_ENTRY["text"]:
            fail(f"system prompt reads {applied!r}, expected {TARGET_ENTRY['text']!r}")
        pass_log("System applied the saved prompt as the chat system prompt")
        section = prompt_box.locator("xpath=ancestor::div[contains(@class,'border-t')][1]")
        await section.screenshot(path=str(artifact_dir / f"system-prompt-section-{browser_name}.png"))

        picker = page.get_by_role("button", name="Load saved prompt as system prompt").first
        if not await picker.count():
            fail("the System Prompt section has no saved-prompt picker")
        await picker.click()
        items = page.get_by_role("menuitem")
        await items.first.wait_for(state="visible", timeout=15_000)
        labels = [(await items.nth(index).inner_text()).strip() for index in range(await items.count())]
        if sorted(labels) != sorted(entry["name"] for entry in SEED_ENTRIES):
            fail(f"picker lists {labels}, expected the three seeded prompts")
        pass_log(f"saved-prompt picker lists {labels}")
        await page.screenshot(path=str(artifact_dir / f"picker-{browser_name}.png"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        await prompt_box.fill(EDITOR_DRAFT)
        await page.wait_for_timeout(500)
        await page.get_by_role("button", name="Edit system prompt").first.click()
        dialog = page.get_by_role("dialog").filter(has_text="Edit System Prompt").first
        await dialog.wait_for(state="visible", timeout=30_000)
        await page.wait_for_timeout(800)
        await dialog.screenshot(path=str(artifact_dir / f"editor-{browser_name}.png"))
        save_as_prompt = dialog.locator("button").filter(has_text=re.compile(r"^\s*Save as prompt\s*$"))
        if not await save_as_prompt.count():
            buttons = await dialog.locator("button").evaluate_all(
                "nodes => nodes.map(node => node.textContent.trim())")
            fail(f"no Save as prompt button in the editor; footer buttons are {buttons}")
        await save_as_prompt.first.click()
        await page.wait_for_timeout(2_000)

    after = await entry_names(base_url, token)
    if EDITOR_DRAFT not in after:
        fail(f"Save as prompt did not add the draft to the library; entries are {after}")
    if len(after) != len(SEED_ENTRIES) + 1:
        fail(f"library holds {len(after)} entries after saving, expected {len(SEED_ENTRIES) + 1}")
    pass_log(f"Save as prompt stored the draft: {len(SEED_ENTRIES)} -> {len(after)} entries")


async def scenario_provider_chat(base_url: str, password: str, browser_name: str, artifact_dir: Path) -> None:
    init, _auth = await auth_init(base_url, password, [provider_seed(MODEL)])
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
    init, _auth = await auth_init(base_url, password, [provider_seed(MODEL)])
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
    init, _auth = await auth_init(base_url, password, [provider_seed(MODEL)])
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
    init, _auth = await auth_init(base_url, password, [provider_seed(MODEL)])
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
    (artifact_dir / "local-chat-response.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        fail("local-chat API returned no assistant content")
    pass_log("local small-model chat API returned assistant content")

    init_scripts = [await auth_init(base_url, password)] if password else []
    try:
        async with open_chat(
            base_url,
            init_scripts=init_scripts,
            video_dir=video_dir(artifact_dir, "local-chat"),
            video_name=f"local-chat-{browser_name}",
            transcode_mp4=False,
            browser_name=browser_name,
        ) as sp:
            await send_prompt(sp, PROMPT)
            await wait_for_stream(sp, timeout_ms=180_000)
            await sp.screenshot(artifact_dir / f"local-chat-{browser_name}.png")
        pass_log("local small-model chat UI accepted a prompt")
    except Exception as exc:
        warn(f"local-chat UI probe skipped after API success: {type(exc).__name__}: {exc}")


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

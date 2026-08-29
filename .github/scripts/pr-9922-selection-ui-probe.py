#!/usr/bin/env python3
"""Playwright proof for PR 9922 On Device selection lifecycles."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import httpx
from playwright.async_api import Route, async_playwright
from studio_test_kit.auth import login, seed_init_script


LABEL = os.environ["PR9922_LABEL"]
EXPECT_ATTACHED = os.environ["PR9922_EXPECT_ATTACHED"] == "true"
HOME = Path(os.environ["UNSLOTH_STUDIO_HOME"])
ARTIFACT_DIR = Path(os.environ["STUDIO_ARTIFACT_DIR"])
DOWNLOAD_STORE_KEY = "unsloth.studio.downloads"
DOWNLOAD_RESET_KEY = "pr9922.reset-download-store"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_unsloth_bin() -> Path:
    candidates = [HOME / "bin" / "unsloth", HOME / "unsloth_studio" / "bin" / "unsloth"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"could not find unsloth CLI under {HOME}")


def wait_for_health(base_url: str, timeout_s: int = 240) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=3) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError("Studio did not become healthy")


def bootstrap_password(log_path: Path) -> str:
    deadline = time.time() + 60
    path = HOME / "auth" / ".bootstrap_password"
    while time.time() < deadline:
        try:
            password = path.read_text(encoding="utf-8").strip()
            if password:
                return password
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError(f"bootstrap password missing; see {log_path}")


async def authenticate(base_url: str, password: str):
    auth = await login(base_url, "unsloth", password)
    if auth.must_change_password:
        replacement = "UnslothStudioCI2026!"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{base_url}/api/auth/change-password",
                headers={"Authorization": f"Bearer {auth.access_token}"},
                json={"current_password": password, "new_password": replacement},
            )
            response.raise_for_status()
            body = response.json()
        auth.access_token = body["access_token"]
        auth.refresh_token = body.get("refresh_token", "")
    return auth


def encoded_id(source: str, model_format: str, repo_id: str) -> str:
    return f"{source}:{model_format}:{urllib.parse.quote(repo_id, safe='')}"


def local_row(repo_id: str, raw_id: bool = False) -> dict:
    row = {
        "id": repo_id,
        "load_id": repo_id,
        "display_name": repo_id.split("/", 1)[-1],
        "path": f"/tmp/models--{repo_id.replace('/', '--')}",
        "source": "hf_cache",
        "model_id": repo_id,
        "model_format": "unknown",
        "runtime": "unknown",
        "size_bytes": 50,
        "partial": True,
        "partial_transport": "http",
        "partial_resumable": True,
    }
    if not raw_id:
        row["inventory_id"] = encoded_id("hf_cache", "unknown", repo_id)
    return row


def cached_row(repo_id: str, model_format: str, partial: bool) -> dict:
    runtime = "llama_cpp" if model_format == "gguf" else "transformers"
    return {
        "repo_id": repo_id,
        "inventory_id": encoded_id("cache", model_format, repo_id),
        "load_id": repo_id,
        "model_format": model_format,
        "runtime": runtime,
        "format_variant": "Q4_K_M" if model_format == "gguf" else None,
        "capabilities": {
            "can_train": model_format == "safetensors",
            "can_chat": True,
            "can_delete": True,
            "can_download": True,
            "requires_variant": model_format == "gguf",
        },
        "size_bytes": 100 if not partial else 50,
        "cache_path": f"/tmp/cache/{repo_id.replace('/', '--')}",
        "partial": partial,
        "partial_transport": "http" if partial else None,
        "partial_resumable": partial,
        "pipeline_tag": "text-generation",
        "tags": ["transformers"],
        "library_name": "transformers",
    }


def persisted_running_job(repo_id: str, variant: str | None = None) -> str:
    key = f"model:{repo_id.strip().lower()}"
    if variant:
        key += f"#{variant.strip().lower()}"
    job = {
        "key": key,
        "kind": "model",
        "repoId": repo_id,
        "variant": variant,
        "state": "running",
        "downloadedBytes": 25,
        "completedBytes": 20,
        "expectedBytes": 100,
        "fraction": 0.25,
        "error": None,
        "startedAt": 1,
        "transport": "http",
        "measuredTransfer": True,
    }
    return json.dumps(
        {
            "state": {
                "jobs": {key: job},
                "conflicts": {},
                "completedHintSignature": "",
                "completedInventoryHints": [],
            },
            "version": 2,
        }
    )


def persisted_hybrid_running_jobs(repo_id: str) -> str:
    store = json.loads(persisted_running_job(repo_id, "Q4_K_M"))
    gguf_key, gguf_job = next(iter(store["state"]["jobs"].items()))
    gguf_job["inventoryKind"] = "gguf"
    scope_key = f"model:{repo_id.strip().lower()}#@diffusion"
    store["state"]["jobs"][scope_key] = {
        **gguf_job,
        "key": scope_key,
        "variant": "@diffusion",
        "inventoryKind": "model",
        "scopedFiles": ["transformer/model.safetensors"],
        "startedAt": 2,
    }
    store["state"]["jobs"][gguf_key] = gguf_job
    return json.dumps(store)


def model_metadata(repo_id: str) -> dict:
    return {
        "id": repo_id,
        "modelId": repo_id,
        "author": repo_id.split("/", 1)[0],
        "sha": "0123456789abcdef",
        "lastModified": "2026-08-29T00:00:00.000Z",
        "createdAt": "2026-08-01T00:00:00.000Z",
        "downloads": 10,
        "downloadsAllTime": 100,
        "likes": 2,
        "pipeline_tag": "text-generation",
        "library_name": "transformers",
        "tags": ["transformers", "text-generation"],
        "private": False,
        "gated": False,
        "siblings": [],
        "safetensors": {"total": 100, "parameters": {"F16": 100}},
        "cardData": {"license": "apache-2.0"},
    }


async def set_download_store(page, value: str | None) -> None:
    await page.evaluate(
        """([key, resetKey, value]) => {
          if (value === null) {
            localStorage.removeItem(key);
            localStorage.setItem(resetKey, "1");
          } else {
            localStorage.setItem(key, value);
          }
        }""",
        [DOWNLOAD_STORE_KEY, DOWNLOAD_RESET_KEY, value],
    )


async def wait_selected(page, leaf: str) -> None:
    await page.get_by_role("heading", name=leaf, exact=True).wait_for(
        state="visible", timeout=30_000
    )


async def wait_url_model(page, expected: str) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        actual = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get("model", [None])[0]
        if actual == expected:
            return
        await page.wait_for_timeout(200)
    raise AssertionError(f"URL model did not become {expected!r}: {page.url}")


async def assert_one_selected_row(page, leaf: str) -> None:
    rows = page.get_by_role("button", name=leaf, exact=True)
    if await rows.count() != 1:
        raise AssertionError(f"expected one deduplicated {leaf} row, got {await rows.count()}")
    parent = rows.first.locator("xpath=..")
    if await parent.get_attribute("data-selected") is None:
        raise AssertionError(f"{leaf} row is not selected")


async def drive(base_url: str, init_script: str) -> dict:
    state = {
        "phase": "local",
        "repo": "unsloth/Selection-Lifecycle-Model",
        "raw_id": False,
        "server_state": "running",
        "inventory_requests": 0,
        "start_requests": 0,
        "cancel_requests": 0,
    }

    async def route_api(route: Route) -> None:
        request = route.request
        parsed = urllib.parse.urlparse(request.url)
        path = parsed.path
        repo_id = state["repo"]
        phase = state["phase"]

        if parsed.netloc == "huggingface.co" and path.startswith("/api/models/"):
            await route.fulfill(json=model_metadata(repo_id))
            return
        if path == "/api/hub/local":
            state["inventory_requests"] += 1
            models = [] if phase == "cached_partial" else [local_row(repo_id, state["raw_id"])]
            await route.fulfill(
                json={"models_dir": "/tmp/models", "hf_cache_dir": "/tmp/hf", "lmstudio_dirs": [], "models": models}
            )
            return
        if path == "/api/hub/cached-models":
            state["inventory_requests"] += 1
            rows = []
            if phase in {"complete", "hybrid"}:
                rows = [cached_row(repo_id, "safetensors", False)]
            elif phase == "cached_partial":
                rows = [cached_row(repo_id, "safetensors", True)]
            await route.fulfill(json={"cached": rows})
            return
        if path == "/api/hub/cached-gguf":
            state["inventory_requests"] += 1
            rows = (
                [cached_row(repo_id, "gguf", False)]
                if phase in {"complete_gguf", "hybrid"}
                else []
            )
            await route.fulfill(json={"cached": rows})
            return
        if path == "/api/hub/active-downloads":
            await route.fulfill(json={"downloads": []})
            return
        if path == "/api/hub/datasets/active-downloads":
            await route.fulfill(json={"downloads": []})
            return
        if path == "/api/hub/download-status":
            await route.fulfill(json={"state": state["server_state"], "generation": 1})
            return
        if path in {"/api/hub/download-progress", "/api/hub/gguf-download-progress"}:
            complete = state["server_state"] == "complete"
            await route.fulfill(
                json={
                    "downloaded_bytes": 100 if complete else 25,
                    "completed_bytes": 100 if complete else 20,
                    "complete_on_disk": complete,
                    "expected_bytes": 100,
                    "progress": 1 if complete else 0.25,
                    "cache_path": f"/tmp/cache/{repo_id.replace('/', '--')}",
                    "target_present": True,
                    "cache_measured": True,
                }
            )
            return
        if path == "/api/studio/download-transport-capabilities":
            await route.fulfill(
                json={
                    "http": {"available": True, "reason": None},
                    "xet": {"available": False, "reason": "disabled in UI proof"},
                    "auto_resolves_to": "http",
                    "auto_reason": None,
                    "partials_resumable": True,
                }
            )
            return
        if path == "/api/hub/transport-status":
            await route.fulfill(json={"has_partial": True, "last_transport": "http", "resumable": True})
            return
        if path == "/api/hub/download" and request.method == "POST":
            state["start_requests"] += 1
            state["server_state"] = "running"
            await route.fulfill(json={"state": "running", "accepted": True, "generation": 1, "job_key": "model:test"})
            return
        if path == "/api/hub/download/cancel" and request.method == "POST":
            state["cancel_requests"] += 1
            state["server_state"] = "cancelled"
            await route.fulfill(json={"state": "cancelling", "job_key": "model:test"})
            return
        if path == "/api/hub/gguf-variants":
            await route.fulfill(
                json={
                    "repo_id": repo_id,
                    "variants": [
                        {
                            "filename": "model-Q4_K_M.gguf",
                            "quant": "Q4_K_M",
                            "display_label": "Q4_K_M",
                            "size_bytes": 100,
                            "downloaded": phase == "hybrid",
                            "partial": phase != "hybrid",
                            "partial_transport": "http",
                            "partial_resumable": True,
                        }
                    ],
                    "has_vision": False,
                    "default_variant": "Q4_K_M",
                }
            )
            return
        await route.continue_()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1500, "height": 1000})
        await context.add_init_script(init_script)
        await context.add_init_script(
            f"""if (localStorage.getItem({json.dumps(DOWNLOAD_RESET_KEY)}) === "1") {{
              localStorage.removeItem({json.dumps(DOWNLOAD_STORE_KEY)});
              localStorage.removeItem({json.dumps(DOWNLOAD_RESET_KEY)});
            }}"""
        )
        await context.route("**/*", route_api)
        page = await context.new_page()

        repo_id = state["repo"]
        leaf = repo_id.split("/", 1)[1]
        await page.goto(f"{base_url}/hub?tab=downloaded", wait_until="domcontentloaded")
        row = page.get_by_role("button", name=leaf, exact=True)
        await row.wait_for(state="visible", timeout=30_000)
        await row.click()
        await wait_selected(page, leaf)
        initial_model = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)["model"][0]

        state["phase"] = "running"
        state["server_state"] = "running"
        await set_download_store(page, persisted_running_job(repo_id, "Q4_K_M"))
        await page.reload(wait_until="domcontentloaded")

        attached = True
        try:
            await wait_selected(page, leaf)
        except Exception:
            attached = False
        if attached != EXPECT_ATTACHED:
            raise AssertionError(f"running selection attached={attached}, expected {EXPECT_ATTACHED}")

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        running_shot = ARTIFACT_DIR / f"{LABEL}_running_selection.png"
        await page.screenshot(path=str(running_shot), full_page=True)
        facts = {
            "label": LABEL,
            "initial_model": initial_model,
            "running_selection_attached": attached,
            "running_screenshot": running_shot.name,
        }

        if not EXPECT_ATTACHED:
            await page.get_by_text("Select a model", exact=True).wait_for(state="visible")
            (ARTIFACT_DIR / f"{LABEL}_facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
            await context.close()
            await browser.close()
            return facts

        await assert_one_selected_row(page, leaf)
        await wait_url_model(page, encoded_id("download", "gguf", repo_id))

        stop = page.get_by_role("button", name="Pause download", exact=True).first
        await stop.wait_for(state="visible", timeout=20_000)
        await stop.click()
        deadline = time.time() + 10
        while state["cancel_requests"] < 1 and time.time() < deadline:
            await page.wait_for_timeout(100)
        if state["cancel_requests"] != 1:
            raise AssertionError("cancel endpoint was not called")
        state["phase"] = "local"
        await set_download_store(page, None)
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, leaf)

        state["phase"] = "running"
        state["server_state"] = "running"
        await set_download_store(page, persisted_running_job(repo_id, "Q4_K_M"))
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, leaf)
        await assert_one_selected_row(page, leaf)

        state["phase"] = "complete_gguf"
        state["server_state"] = "complete"
        await set_download_store(page, persisted_running_job(repo_id, "Q4_K_M"))
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, leaf)
        await wait_url_model(page, encoded_id("cache", "gguf", repo_id))
        await assert_one_selected_row(page, leaf)
        completion_shot = ARTIFACT_DIR / f"{LABEL}_completed_selection.png"
        await page.screenshot(path=str(completion_shot), full_page=True)

        state["phase"] = "hybrid"
        await set_download_store(page, None)
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, leaf)
        await wait_url_model(page, encoded_id("cache", "gguf", repo_id))

        format_filter = page.get_by_role("button", name="Format filter")
        await format_filter.click()
        await page.get_by_role("option", name="Safetensors", exact=True).click()
        await page.get_by_text("Current selection is hidden by the active filters or search.", exact=True).wait_for(
            state="visible", timeout=10_000
        )
        await wait_selected(page, leaf)

        unknown_id = encoded_id("hf_cache", "unknown", repo_id)
        await page.goto(
            f"{base_url}/hub?tab=downloaded&model={urllib.parse.quote(unknown_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await page.get_by_text("Select a model", exact=True).wait_for(state="visible", timeout=20_000)
        malformed_id = "hf_cache:unknown:Org%2"
        await page.goto(
            f"{base_url}/hub?tab=downloaded&model={urllib.parse.quote(malformed_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await page.get_by_text("Select a model", exact=True).wait_for(state="visible", timeout=20_000)

        format_filter = page.get_by_role("button", name="Format filter")
        await format_filter.click()
        await page.get_by_role("option", name="All formats", exact=True).click()

        state.update(phase="local", repo="unsloth/Hybrid-Live-Formats", raw_id=False, server_state="running")
        hybrid_repo = state["repo"]
        hybrid_leaf = hybrid_repo.split("/", 1)[1]
        await set_download_store(page, persisted_hybrid_running_jobs(hybrid_repo))
        gguf_live_id = encoded_id("download", "gguf", hybrid_repo)
        await page.goto(
            f"{base_url}/hub?tab=downloaded&model={urllib.parse.quote(gguf_live_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await wait_selected(page, hybrid_leaf)
        hybrid_rows = page.get_by_role("button", name=hybrid_leaf, exact=True)
        if await hybrid_rows.count() != 2:
            raise AssertionError(f"expected two hybrid live rows, got {await hybrid_rows.count()}")
        await wait_url_model(page, gguf_live_id)

        model_live_id = encoded_id("download", "safetensors", hybrid_repo)
        await page.goto(
            f"{base_url}/hub?tab=downloaded&model={urllib.parse.quote(model_live_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await wait_selected(page, hybrid_leaf)
        if await hybrid_rows.count() != 2:
            raise AssertionError("hybrid live rows collapsed after selecting the model format")
        await wait_url_model(page, model_live_id)

        state.update(phase="local", repo="unsloth/Selection-Safetensors-Model", raw_id=False, server_state="running")
        safetensors_repo = state["repo"]
        safetensors_leaf = safetensors_repo.split("/", 1)[1]
        await set_download_store(page, None)
        await page.goto(f"{base_url}/hub?tab=downloaded", wait_until="domcontentloaded")
        await page.get_by_role("button", name=safetensors_leaf, exact=True).click()
        await wait_selected(page, safetensors_leaf)
        state["phase"] = "running"
        await set_download_store(page, persisted_running_job(safetensors_repo))
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, safetensors_leaf)
        await wait_url_model(page, encoded_id("download", "safetensors", safetensors_repo))
        await assert_one_selected_row(page, safetensors_leaf)

        state.update(phase="local", repo="unsloth/Legacy-Raw-Selection", raw_id=True, server_state="running")
        raw_repo = state["repo"]
        raw_leaf = raw_repo.split("/", 1)[1]
        await set_download_store(page, None)
        await page.goto(f"{base_url}/hub?tab=downloaded", wait_until="domcontentloaded")
        await page.get_by_role("button", name=raw_leaf, exact=True).click()
        try:
            await wait_selected(page, raw_leaf)
        except Exception:
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(ARTIFACT_DIR / "after_legacy_raw_failure.png"), full_page=True)
            headings = await page.get_by_role("heading").all_inner_texts()
            raise AssertionError(
                f"legacy raw selection failed: url={page.url!r}, headings={headings!r}"
            )
        await wait_url_model(page, raw_repo)
        state["phase"] = "running"
        await set_download_store(page, persisted_running_job(raw_repo))
        await page.reload(wait_until="domcontentloaded")
        await wait_selected(page, raw_leaf)
        await assert_one_selected_row(page, raw_leaf)

        state.update(phase="cached_partial", repo="unsloth/UI-Resume-Selection", raw_id=False, server_state="cancelled")
        resume_repo = state["repo"]
        resume_leaf = resume_repo.split("/", 1)[1]
        await set_download_store(page, None)
        await page.goto(f"{base_url}/hub?tab=downloaded", wait_until="domcontentloaded")
        await page.get_by_role("button", name=resume_leaf, exact=True).click()
        await wait_selected(page, resume_leaf)
        await page.get_by_role("button", name="Resume", exact=True).click()
        deadline = time.time() + 15
        while state["start_requests"] < 1 and time.time() < deadline:
            await page.wait_for_timeout(100)
        if state["start_requests"] != 1:
            raise AssertionError("Resume did not call the download start endpoint")
        await wait_selected(page, resume_leaf)
        await assert_one_selected_row(page, resume_leaf)
        await page.get_by_role("button", name="Pause download", exact=True).first.click()
        deadline = time.time() + 10
        while state["cancel_requests"] < 2 and time.time() < deadline:
            await page.wait_for_timeout(100)
        if state["cancel_requests"] < 2:
            raise AssertionError("resumed download did not call cancel")
        await wait_selected(page, resume_leaf)

        facts.update(
            {
                "cancel_survived": True,
                "resume_survived": True,
                "completion_survived": True,
                "deduplicated_row_count": 1,
                "unknown_to_safetensors": True,
                "unknown_to_gguf": True,
                "legacy_raw_id": True,
                "malformed_id_rejected": True,
                "ambiguous_unknown_rejected": True,
                "hybrid_live_format_rows": 2,
                "filtered_selection_retained": True,
                "ui_resume_start_requests": state["start_requests"],
                "cancel_requests": state["cancel_requests"],
                "inventory_requests": state["inventory_requests"],
                "completion_screenshot": completion_shot.name,
            }
        )
        (ARTIFACT_DIR / f"{LABEL}_facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
        await context.close()
        await browser.close()
        return facts


async def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = ARTIFACT_DIR / "studio.log"
    environment = os.environ.copy()
    environment["UNSLOTH_STUDIO_HOME"] = str(HOME)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(find_unsloth_bin()), "studio", "-H", "127.0.0.1", "-p", str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
    try:
        wait_for_health(base_url)
        auth = await authenticate(base_url, bootstrap_password(log_path))
        init_script = seed_init_script(
            auth,
            [],
            extra_local_storage={
                "unsloth.hub.allModelsView": "split",
                "unsloth.hub.modelsTab": "downloaded",
            },
        )
        facts = await drive(base_url, init_script)
        print(json.dumps(facts, sort_keys=True), flush=True)
    finally:
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except OSError:
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    asyncio.run(main())

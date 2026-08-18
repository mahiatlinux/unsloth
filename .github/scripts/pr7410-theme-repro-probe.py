#!/usr/bin/env python3
"""Live Studio probe for unslothai/unsloth PR 7410 (Local Model picker theme styles).

Two assertions, both self-referential so they hold under any palette:

  A. dark mode, Local Model trigger. Focusing the nested input must not change the
     trigger's surface. InputGroup applies
     `dark:has-[[data-slot=input-group-control]:focus-visible]:bg-white/[0.12]` to its
     own root, which outranks `dark:bg-foreground` on the trigger, so before the PR the
     pill turns dark the moment the input takes focus.
  B. light mode, Local Model dropdown. The highlight must belong to the panel it is
     drawn on: the highlighted row's text must keep roughly the luminance of an
     unhighlighted row, and the highlight fill must keep roughly the luminance of the
     panel behind it. ComboboxItem highlights with `data-highlighted:bg-accent
     data-highlighted:text-accent-foreground`, and DARK_COMBOBOX_CONTENT only overrode
     those under `dark:`, so before the PR the dark panel drew the light theme's opaque
     grey bar with near-black text on it.

The dropdown needs rows, so the probe seeds three fake safetensors models and registers
the folder through POST /api/models/scan-folders. The theme is pinned through
PUT /api/settings/personalization as well as localStorage: use-personalization-sync
loads the stored appearance on boot and calls setTheme with it, so a seeded localStorage
alone is overwritten by whatever the previous pass saved.

Do not print bootstrap passwords or auth tokens.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx
from studio_test_kit.auth import login, seed_init_script
from studio_test_kit.ui import open_chat

# WCAG relative-luminance gaps, wide enough to survive a palette tweak and far below
# the inversion the unfixed styles produce (0.97 on text, 0.83 on the fill)
MAX_TEXT_LUMINANCE_GAP = 0.15
MAX_FILL_LUMINANCE_GAP = 0.25

# anchored on the tour id, not the placeholder: the placeholder is i18n text and reads
# "scanning local and cached models" until the first scan returns
TRIGGER_SEL = "[data-tour=studio-local-model] [data-slot=input-group]"
CONTENT_SEL = "[data-slot=combobox-content]"
ITEM_SEL = "[data-slot=combobox-item]"

SEED_MODELS = ("qwen3-0.6b-demo", "llama-3.2-1b-demo", "smollm2-135m-demo")
# fixed future mtime keeps the seeded rows at the head of a list that sorts on updated_at
SEED_MTIME = 2_208_988_800.0

failures: list[str] = []


def pass_log(message: str) -> None:
    print(f"PASS {message}", flush=True)


def warn(message: str) -> None:
    print(f"WARN {message}", flush=True)


def record_failure(message: str) -> None:
    failures.append(message)
    print(f"FAIL {message}", file=sys.stderr, flush=True)


def fail(message: str) -> None:
    record_failure(message)
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
        try:
            text = (home / rel).read_text(encoding="utf-8").strip()
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


def wait_for_health(base_url: str, timeout_s: int = 300) -> str:
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


def studio_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["UNSLOTH_STUDIO_HOME"] = str(home)
    env.pop("STUDIO_HOME", None)
    return env


def start_studio(home: Path, log_path: Path, port: int) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    kwargs: dict = {"stdout": handle, "stderr": subprocess.STDOUT, "env": studio_env(home)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    cmd = [str(find_unsloth_bin(home)), "studio", "-H", "127.0.0.1", "-p", str(port)]
    print("Launching: " + " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, **kwargs)
    handle.close()
    return proc


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
        proc.kill()


def seed_scan_folder(root: Path) -> Path:
    seed = (root / "seed_models").resolve()
    for index, name in enumerate(SEED_MODELS):
        directory = seed / name
        directory.mkdir(parents=True, exist_ok=True)
        config = directory / "config.json"
        if not config.exists():
            config.write_text(
                json.dumps({"model_type": "llama", "architectures": ["LlamaForCausalLM"]}),
                encoding="utf-8",
            )
        weights = directory / "model.safetensors"
        if not weights.exists():
            weights.write_bytes(b"\x00" * 1024)
        stamp = SEED_MTIME - index * 60
        os.utime(directory, (stamp, stamp))
    return seed


async def api(client: httpx.AsyncClient, method: str, base_url: str, path: str,
              token: str, payload: dict | None = None) -> httpx.Response:
    return await client.request(
        method,
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


async def to_rgba(page, value: str) -> tuple[float, float, float, float]:
    """Normalise any computed colour to sRGB + alpha by painting it in the page.

    getComputedStyle hands back whatever colour space the sheet used (this build emits
    oklab and oklch), so the browser, not a regex, has to do the conversion.
    """
    result = await page.evaluate(
        """(value) => {
            const canvas = document.createElement('canvas');
            canvas.width = 1;
            canvas.height = 1;
            const ctx = canvas.getContext('2d', {willReadFrequently: true});
            ctx.globalCompositeOperation = 'copy';
            ctx.fillStyle = value;
            ctx.fillRect(0, 0, 1, 1);
            const data = ctx.getImageData(0, 0, 1, 1).data;
            return [data[0], data[1], data[2], data[3] / 255];
        }""",
        value,
    )
    return tuple(float(component) for component in result)  # type: ignore[return-value]


def relative_luminance(rgba: tuple[float, float, float, float]) -> float:
    def channel(raw: float) -> float:
        c = raw / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(rgba[0]) + 0.7152 * channel(rgba[1]) + 0.0722 * channel(rgba[2])


def composited_luminance(fill: tuple[float, float, float, float],
                         behind: tuple[float, float, float, float]) -> float:
    """Luminance of a possibly translucent fill drawn over an opaque background."""
    alpha = fill[3]
    return alpha * relative_luminance(fill) + (1 - alpha) * relative_luminance(behind)


async def computed(locator, props: list[str]) -> dict:
    return await locator.evaluate(
        """(el, props) => {
            const cs = getComputedStyle(el);
            const out = {};
            for (const p of props) out[p] = cs.getPropertyValue(p).trim();
            return out;
        }""",
        props,
    )


async def open_studio_page(sp, base_url: str, artifact_dir: Path, tag: str):
    page = sp.page
    await page.goto(f"{base_url}/studio", wait_until="domcontentloaded")
    try:
        await page.locator(TRIGGER_SEL).first.wait_for(state="visible", timeout=90_000)
    except Exception:
        await dump_page(page, artifact_dir, tag)
        raise
    return page


async def dump_page(page, artifact_dir: Path, tag: str) -> None:
    """Screenshot and text-dump the page a selector could not find itself in."""
    try:
        await page.screenshot(path=str(artifact_dir / f"debug-{tag}.png"), full_page=True)
        text = await page.evaluate("document.body ? document.body.innerText : ''")
        (artifact_dir / f"debug-{tag}.txt").write_text(
            f"url: {page.url}\n\n{text[:4000]}", encoding="utf-8"
        )
        print(f"WARN wrote debug-{tag}.png/.txt for {page.url}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- diagnostics must not mask the real error
        warn(f"could not dump the page state: {type(exc).__name__}: {exc}")


async def assert_theme(page, theme: str) -> str:
    await page.wait_for_timeout(1_500)
    html_class = await page.evaluate("document.documentElement.className")
    if theme not in html_class.split():
        fail(f"asked for the {theme} theme and the document is '{html_class}'")
    return html_class


async def dark_pass(base_url: str, init: str, browser: str, artifact_dir: Path) -> dict:
    """Measure the trigger surface before and after the input takes focus."""
    async with open_chat(base_url, init_scripts=[init], browser_name=browser,
                         viewport=(1440, 900)) as sp:
        page = await open_studio_page(sp, base_url, artifact_dir, f"dark-{browser}")
        await assert_theme(page, "dark")
        trigger = page.locator(TRIGGER_SEL).first
        resting = (await computed(trigger, ["background-color"]))["background-color"]

        field = page.locator(f"{TRIGGER_SEL} input").first
        await field.click()
        await page.wait_for_timeout(400)
        focus_visible = await field.evaluate("el => el.matches(':focus-visible')")
        if not focus_visible:
            await page.keyboard.press("Escape")
            await field.evaluate("el => el.blur()")
            await page.keyboard.press("Tab")
            await field.focus()
            focus_visible = await field.evaluate("el => el.matches(':focus-visible')")
        if not focus_visible:
            fail("the Local Model input never matched :focus-visible, so the surface "
                 "under test was never shown")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        focused = (await computed(trigger, ["background-color"]))["background-color"]
        await page.screenshot(path=str(artifact_dir / f"dark-focused-{browser}.png"),
                              clip={"x": 0, "y": 120, "width": 1440, "height": 380})

    result = {"resting": resting, "focused": focused, "focus_visible": focus_visible}
    if focused != resting:
        record_failure(
            f"dark mode: focusing the Local Model input changed the trigger surface from "
            f"{resting} to {focused}; the trigger should hold one surface in both states"
        )
    else:
        pass_log(f"dark mode: trigger surface stayed {focused} while the input was focused")
    return result


async def light_pass(base_url: str, init: str, browser: str, artifact_dir: Path) -> dict:
    """Measure the highlighted row against an unhighlighted one in the same panel."""
    async with open_chat(base_url, init_scripts=[init], browser_name=browser,
                         viewport=(1440, 900)) as sp:
        page = await open_studio_page(sp, base_url, artifact_dir, f"light-{browser}")
        await assert_theme(page, "light")

        field = page.locator(f"{TRIGGER_SEL} input").first
        await field.click()
        content = page.locator(CONTENT_SEL).first
        try:
            await content.wait_for(state="visible", timeout=8_000)
        except Exception:  # noqa: BLE001 -- the list may need an explicit open
            await page.keyboard.press("ArrowDown")
            await content.wait_for(state="visible", timeout=15_000)
        highlighted = page.locator(f"{ITEM_SEL}[data-highlighted]").first
        try:
            await highlighted.wait_for(state="visible", timeout=8_000)
        except Exception:  # noqa: BLE001 -- autoHighlight can lose a race with the scan
            await page.keyboard.press("ArrowDown")
            await highlighted.wait_for(state="visible", timeout=15_000)
        plain = page.locator(f"{ITEM_SEL}:not([data-highlighted])").first
        await plain.wait_for(state="visible", timeout=15_000)
        await page.wait_for_timeout(500)

        item_count = await page.locator(ITEM_SEL).count()
        highlighted_style = await computed(highlighted, ["background-color", "color"])
        plain_style = await computed(plain, ["background-color", "color"])
        accent = await computed(content, ["--accent", "--accent-foreground"])
        panel_style = await computed(content, ["background-color", "color"])
        await page.screenshot(path=str(artifact_dir / f"light-dropdown-{browser}.png"),
                              clip={"x": 0, "y": 120, "width": 1440, "height": 500})

        panel_fill = await to_rgba(page, panel_style["background-color"])
        text_gap = abs(
            relative_luminance(await to_rgba(page, highlighted_style["color"]))
            - relative_luminance(await to_rgba(page, plain_style["color"]))
        )
        fill_gap = abs(
            composited_luminance(
                await to_rgba(page, highlighted_style["background-color"]), panel_fill
            )
            - relative_luminance(panel_fill)
        )

    result = {"item_count": item_count, "highlighted": highlighted_style,
              "plain": plain_style, "panel": panel_style, "content_accent": accent,
              "text_luminance_gap": round(text_gap, 4),
              "fill_luminance_gap": round(fill_gap, 4)}

    if text_gap > MAX_TEXT_LUMINANCE_GAP:
        record_failure(
            f"light mode: the highlighted row's text is {highlighted_style['color']} while "
            f"an unhighlighted row in the same panel is {plain_style['color']} "
            f"(luminance gap {text_gap:.2f} > {MAX_TEXT_LUMINANCE_GAP}); the highlight uses "
            f"the light theme's --accent-foreground ({accent.get('--accent-foreground')})"
        )
    else:
        pass_log(
            f"light mode: highlighted text {highlighted_style['color']} stays with the "
            f"panel's {plain_style['color']} (luminance gap {text_gap:.2f})"
        )

    if fill_gap > MAX_FILL_LUMINANCE_GAP:
        record_failure(
            f"light mode: the highlight fill {highlighted_style['background-color']} sits "
            f"{fill_gap:.2f} in luminance from the panel {panel_style['background-color']} "
            f"it is drawn on; --accent is {accent.get('--accent')}"
        )
    else:
        pass_log(
            f"light mode: highlight fill {highlighted_style['background-color']} stays with "
            f"the panel (luminance gap {fill_gap:.2f})"
        )
    return result


async def main() -> None:
    home = Path(os.environ["UNSLOTH_STUDIO_HOME"]).resolve()
    browser = os.environ.get("STUDIO_BROWSER", "chromium")
    artifact_dir = Path(os.environ.get("STUDIO_ARTIFACT_DIR", "studio-live-artifacts")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = artifact_dir / "studio.log"
    proc: subprocess.Popen | None = None
    measurements: dict = {"browser": browser}

    try:
        proc = start_studio(home, log_path, port)
        health_path = wait_for_health(base_url)
        pass_log(f"Studio healthy at {health_path} on {base_url}")

        password = read_bootstrap_password(home, log_path)
        if not password:
            fail("could not read the Studio bootstrap password from the home or the log")
        auth = await login(base_url, "unsloth", password)
        if auth.must_change_password:
            new_password = os.environ.get("STUDIO_TEST_PASSWORD", "UnslothStudioCI2026!")
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{base_url}/api/auth/change-password",
                    headers={"Authorization": f"Bearer {auth.access_token}"},
                    json={"current_password": password, "new_password": new_password},
                )
                response.raise_for_status()
                body = response.json()
            auth.access_token = body["access_token"]
            auth.refresh_token = body.get("refresh_token", "")
        pass_log("Studio API login succeeded")

        seed = seed_scan_folder(home.parent)
        async with httpx.AsyncClient(timeout=120) as client:
            added = await api(client, "POST", base_url, "/api/models/scan-folders",
                              auth.access_token, {"path": str(seed)})
            if added.status_code >= 400 and added.status_code not in (400, 409):
                fail(f"could not register the seeded scan folder: {added.status_code}")
            listing = await api(client, "GET", base_url, "/api/models/local",
                                auth.access_token)
            listing.raise_for_status()
            models = listing.json().get("models", [])
            seeded = [m for m in models if str(m.get("path", "")).startswith(str(seed))]
            measurements["seeded_model_count"] = len(seeded)
            measurements["listed_model_count"] = len(models)
            if len(seeded) != len(SEED_MODELS):
                fail(f"seeded {len(SEED_MODELS)} models but the picker lists {len(seeded)}; "
                     "the dropdown rows this PR restyles would not be there")
            pass_log(f"{len(seeded)} seeded local models are listed by the picker")

            for theme, runner in (("dark", dark_pass), ("light", light_pass)):
                themed = await api(client, "PUT", base_url,
                                   "/api/settings/personalization", auth.access_token,
                                   {"appearance": {"theme": theme}})
                themed.raise_for_status()
                init = seed_init_script(auth, [], extra_local_storage={"theme": theme})
                measurements[theme] = await runner(base_url, init, browser, artifact_dir)

        (artifact_dir / f"pr7410-measurements-{browser}.json").write_text(
            json.dumps(measurements, indent=2), encoding="utf-8"
        )
    finally:
        stop_process(proc)

    if failures:
        print(f"FAIL {len(failures)} assertion(s) failed", file=sys.stderr, flush=True)
        raise SystemExit(1)
    pass_log("PR 7410 Local Model picker theme assertions all held")


if __name__ == "__main__":
    asyncio.run(main())

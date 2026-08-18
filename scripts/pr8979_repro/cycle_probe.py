#!/usr/bin/env python3
"""Probe whether a module-scope read of SIDEBAR_ORGANIZATION_STORAGE_KEY throws.

Builds a vite smoke entry (no backend, no auth, the same shape as the repo's own
smoke-*.html harnesses), optionally perturbs the tree, serves it with the vite dev
server and loads it in Chromium. Reports one JSON line per variant.

The failure under test is a temporal dead zone read during module evaluation:
`Cannot access 'SIDEBAR_ORGANIZATION_STORAGE_KEY' before initialization`. Nothing
catches it, so the page renders nothing at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

TDZ_MARKER = "SIDEBAR_ORGANIZATION_STORAGE_KEY"

SMOKE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>cycle probe</title></head>
<body><div id="root"></div><script type="module" src="/smoke-cycle-main.tsx"></script></body></html>
"""

# One entry per variant. The entry is the module the cycle is ENTERED from, which is the
# only thing that decides whether the key is still in its temporal dead zone when
# general-tab.tsx builds its top-level const array.
ENTRIES = {
    # Entering at the chat barrel, the way the router does.
    "barrel-first": """import { ChatPage } from "@/features/chat";
import { createRoot } from "react-dom/client";
createRoot(document.getElementById("root")!).render(
  <div data-testid="probe">entered at the chat barrel: {typeof ChatPage}</div>,
);
""",
    # Entering at the store, which only differs once the store is itself in the cycle.
    "store-first": """import { useSidebarOrganizationStore } from "@/features/chat/stores/sidebar-organization-store";
import { createRoot } from "react-dom/client";
createRoot(document.getElementById("root")!).render(
  <div data-testid="probe">entered at the store: {typeof useSidebarOrganizationStore}</div>,
);
""",
}

GENERAL_TAB = "src/features/settings/tabs/general-tab.tsx"
STORE = "src/features/chat/stores/sidebar-organization-store.ts"


def patch_general_tab_to_barrel(frontend: Path) -> None:
    """Read the key through the chat barrel, the form #8932 shipped and #8956 replaced."""
    path = frontend / GENERAL_TAB
    text = path.read_text()
    for old in (
        'import { SIDEBAR_ORGANIZATION_STORAGE_KEY } from "@/features/chat/stores/sidebar-organization-store";',
        'import { SIDEBAR_ORGANIZATION_STORAGE_KEY } from "@/features/chat/stores/sidebar-organization-keys";',
    ):
        if old in text:
            path.write_text(text.replace(
                old, 'import { SIDEBAR_ORGANIZATION_STORAGE_KEY } from "@/features/chat";'))
            return
    raise SystemExit(f"no key import found to rewrite in {path}")


def patch_store_into_cycle(frontend: Path) -> None:
    """Give the store an import that puts it in the cycle, which is how this regresses."""
    path = frontend / STORE
    text = path.read_text()
    marker = 'import { create } from "zustand";'
    if marker not in text:
        raise SystemExit(f"store shape changed, cannot perturb {path}")
    path.write_text(text.replace(marker, 'import "@/features/settings";\n' + marker, 1))


PATCHES = {
    "none": lambda _f: None,
    "general-tab-via-barrel": patch_general_tab_to_barrel,
    "store-in-cycle": patch_store_into_cycle,
}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def write_entry(frontend: Path, entry: str) -> None:
    (frontend / "smoke-cycle.html").write_text(SMOKE_HTML)
    (frontend / "smoke-cycle-main.tsx").write_text(ENTRIES[entry])


def start_vite(frontend: Path, port: int, log: Path):
    handle = log.open("w")
    proc = subprocess.Popen(
        ["npx", "vite", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
        cwd=frontend, stdout=handle, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"vite exited early:\n{log.read_text()[-2000:]}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return proc
        except OSError:
            time.sleep(1)
    proc.kill()
    raise SystemExit("vite never bound its port")


async def load(port: int, shot: Path | None) -> dict:
    from playwright.async_api import async_playwright

    errors: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto(f"http://127.0.0.1:{port}/smoke-cycle.html", wait_until="load")
        # A fixed settle, not a wait on any element: the failing side has no element to
        # wait for, and a locator timeout would abort instead of recording the blank page.
        await page.wait_for_timeout(6_000)
        root = await page.evaluate("document.getElementById('root')?.innerHTML ?? ''")
        if shot is not None:
            await page.screenshot(path=str(shot))
        await browser.close()
    return {
        "rendered": bool(root.strip()),
        "root_html_len": len(root),
        "tdz": next((e for e in errors if TDZ_MARKER in e), ""),
        "first_error": errors[0][:200] if errors else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frontend", type=Path, required=True)
    ap.add_argument("--entry", choices=sorted(ENTRIES), required=True)
    ap.add_argument("--patch", choices=sorted(PATCHES), default="none")
    ap.add_argument("--label", required=True)
    ap.add_argument("--screenshot", type=Path, default=None)
    ap.add_argument("--log", type=Path, default=Path("vite.log"))
    args = ap.parse_args()

    frontend = args.frontend.resolve()
    PATCHES[args.patch](frontend)
    write_entry(frontend, args.entry)
    port = free_port()
    proc = start_vite(frontend, port, args.log)
    try:
        result = asyncio.run(load(port, args.screenshot))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    result.update(label=args.label, entry=args.entry, patch=args.patch)
    print("PROBE " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

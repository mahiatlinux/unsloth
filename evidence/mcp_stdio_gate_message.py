"""Scene: the MCP servers dialog's error toast when a local command is refused.

PR 8739 is backend-only, and both halves of it surface here.

1. `stdio_mcp_disabled_reason()` replaces one hardcoded string in
   `routes/mcp_servers.py`. `_validate_url` raises it as a 400 detail, and
   `mcp-servers-api.ts` (`parseErrorText` -> `formatFastApiDetail`) puts that detail
   verbatim into the sonner toast's description. So the sentence the user reads IS
   the string this PR changes -- no paraphrase in between.

   Both sides are launched `unsloth studio -p <port> --disable-tools` on loopback.
   That is the configuration the new message exists for: the loopback bind auto-sets
   UNSLOTH_STUDIO_ALLOW_STDIO_MCP=1 (`apply_stdio_mcp_loopback_default`), and the CLI
   tool policy is then what closes the gate (`stdio_mcp_enabled`). BEFORE tells the
   user to set a variable that is already 1; AFTER names the real cause.

2. `_mcp_tool_model_visible()` in `core/inference/tools.py` drops MCP Apps tools
   marked app-only from the specs sent to the model. That has NO UI surface: nothing
   in the app lists the model-facing MCP tool set (the only readers are the prompt
   itself and /api/inference/chat/count_tokens, which needs a loaded GGUF), and the
   dialog's own "Connected (N tools)" count is the unfiltered discovery result. So it
   is measured instead of photographed: the scene reads each home's OWN installed
   `studio/backend/core/inference/tools.py`, execs its `_mcp_specs_for_server`
   against a fixed MCP Apps tool list, and reports how many specs come out. Same
   file the photographed server imports, so the number belongs to that build.

Two shots per side:

  0  the whole 1280x860 viewport -- the Add-server form with the command typed, and
     the toast over its top-right corner
  1  a FIXED clip of the toast corner. Sonner is top-right with `top: 52` on /chat
     and its toasts are 356 px wide, so the box's top-left is a constant and only its
     height moves with the text. A fixed clip keeps both halves the same size, which
     is what stops hstack_images from scaling one of them up.

No weights, no GPU, no downloads: the gate refuses before anything is spawned.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Optional

WORKSPACE = Path(os.environ.get("UNSLOTH_WORKSPACE", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from pr_ui_scenes._common import Session, api_get, api_post  # noqa: E402
from studio_test_kit.auth import seed_init_script  # noqa: E402
from studio_test_kit.ui import open_chat  # noqa: E402

DEFAULT_COMMAND = "npx -y @modelcontextprotocol/server-filesystem /tmp"
DEFAULT_DISPLAY_NAME = "Local filesystem"
# Scheme-less and whitespace-free, so _looks_like_command() is False and the OTHER
# branch of _validate_url answers. Untouched by this PR: it is the control.
CONTROL_ADDRESS = "example.com/mcp"

VIEWPORT = (1280, 860)
# getToastOffsets(): /chat is a HEADER_ROUTE, so top = 52, right = 12; sonner toasts
# are 356 px wide. At 1280 px that puts the box at x 912-1268, y 52. Height grows with
# the description, so the clip is deliberately taller than either message needs.
TOAST_CLIP = {"x": 896, "y": 40, "width": 384, "height": 220}
TOAST = "[data-sonner-toast]"

# A live MCP Apps server's tool list, in the two _meta shapes the PR handles plus the
# two that must survive. Fixed here so both sides are scored on identical input.
FIXTURE_MCP_TOOLS = [
    {
        "name": "get_system_metrics",
        "description": "Read current CPU, memory and disk figures.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "poll_dashboard",
        "description": "Widget-internal poll for the dashboard's own refresh loop.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"ui": {"visibility": ["app"]}},
    },
    {
        "name": "render_dashboard_widget",
        "description": "Render the dashboard widget. Called by the app, not the model.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"ui/visibility": ["app"]},
    },
    {
        "name": "open_dashboard",
        "description": "Open the monitor dashboard.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"ui": {"visibility": ["model", "app"]}},
    },
]


def _post_expecting_error(session: Session, path: str, payload: dict) -> dict:
    """POST and report the refusal as data. The 400 IS the thing being measured."""
    try:
        body = api_post(session, path, payload, timeout=60)
        return {"status": 200, "detail": None, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()[:2000]
        try:
            detail = json.loads(raw).get("detail")
        except ValueError:
            detail = raw
        if isinstance(detail, str):
            detail = " ".join(detail.split())
        return {"status": exc.code, "detail": detail}
    except Exception as exc:  # noqa: BLE001 -- a reading, not a scene failure
        return {"status": None, "detail": f"{type(exc).__name__}: {exc}"[:300]}


def _installed_tools_py(home: Path) -> Optional[Path]:
    """The `tools.py` the photographed server imports, resolved BY that install.

    `install.sh --local` installs the tree editably, so the deployed backend is the
    worktree the side was built from rather than a copy under the home. Asking this
    home's own interpreter for the spec origin is what ties the file to the side that
    was photographed: a guessed path could name the other side's worktree and nothing
    downstream would notice.
    """
    for python in sorted(home.glob("unsloth_studio/bin/python3*")) or sorted(
        home.glob("unsloth_studio/Scripts/python.exe")
    ):
        probe = subprocess.run(
            [str(python), "-c",
             "import importlib.util as u;"
             "s = u.find_spec('studio.backend.core.inference.tools');"
             "print(s.origin if s else '')"],
            text=True, capture_output=True, timeout=300,
        )
        origin = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
        if origin and Path(origin).is_file():
            return Path(origin)
        raise RuntimeError(
            f"{python} could not resolve studio.backend.core.inference.tools\n"
            f"--- stdout ---\n{probe.stdout[-2000:]}\n--- stderr ---\n{probe.stderr[-2000:]}"
        )
    return None


def _model_facing_specs(tools_py: Path, mcp_tools: list[dict]) -> dict:
    """Run this build's own `_mcp_specs_for_server` over `mcp_tools`.

    Only the two functions are exec'd, lifted out by `ast`: importing the real module
    would drag in the whole backend (torch included) for a pure dict transform. The
    module-level names they close over are re-created here exactly as tools.py defines
    them, so a rename upstream fails loudly instead of scoring a stub.
    """
    source = tools_py.read_text()
    tree = ast.parse(source)
    wanted = ("_mcp_tool_model_visible", "_mcp_specs_for_server")
    found = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    }
    if "_mcp_specs_for_server" not in found:
        raise RuntimeError(f"_mcp_specs_for_server not found in {tools_py}")

    class _Logger:
        def __init__(self):
            self.messages: list[str] = []

        def _record(self, msg, *args):
            self.messages.append(msg % args if args else msg)

        warning = debug = info = error = _record

    logger = _Logger()
    namespace: dict = {
        "re": re,
        "logger": logger,
        "MCP_TOOL_PREFIX": "mcp__",
        "_OPENAI_FN_NAME_RE": re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    }
    for name in wanted:
        if name in found:
            module = ast.Module(body=[found[name]], type_ignores=[])
            exec(compile(ast.fix_missing_locations(module), str(tools_py), "exec"), namespace)

    server = {"id": "fixture", "display_name": "System Monitor"}
    specs = namespace["_mcp_specs_for_server"](server, [dict(t) for t in mcp_tools])
    return {
        "count": len(specs),
        "names": [s["function"]["name"].split("__", 2)[-1] for s in specs],
        "has_visibility_filter": "_mcp_tool_model_visible" in found,
        "skipped_log": logger.messages,
    }


async def _fill(page, selector: str, value: str) -> None:
    field = page.locator(selector).first
    await field.wait_for(state="visible", timeout=30_000)
    await field.click()
    await field.fill(value)
    got = await field.input_value()
    if got != value:
        raise RuntimeError(f"{selector} holds {got!r}, expected {value!r}")


async def drive(session: Session, out_dir: Path, label: str,
                command: str = DEFAULT_COMMAND,
                display_name: str = DEFAULT_DISPLAY_NAME,
                **_: object) -> tuple[list[Path], dict]:
    """Photograph the refusal toast, and measure the strings and counts behind it."""
    facts: dict = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- the strings, straight off the photographed server -------------------
    test = _post_expecting_error(session, "/api/mcp/servers/test", {"url": command})
    facts["stdio_gate_test_status"] = test["status"]
    facts["stdio_gate_test_detail"] = test["detail"]
    create = _post_expecting_error(
        session, "/api/mcp/servers/",
        {"display_name": display_name, "url": command, "is_enabled": True},
    )
    facts["stdio_gate_create_status"] = create["status"]
    facts["stdio_gate_create_detail"] = create["detail"]
    control = _post_expecting_error(session, "/api/mcp/servers/test", {"url": CONTROL_ADDRESS})
    facts["control_status"] = control["status"]
    facts["control_detail"] = control["detail"]

    detail = facts["stdio_gate_test_detail"] or ""
    facts["gate_advice_mentions_env_var"] = "UNSLOTH_STUDIO_ALLOW_STDIO_MCP=1" in detail
    facts["gate_advice_names_real_cause"] = "--disable-tools" in detail
    facts["gate_advice_names_remote_access"] = "Remote Access" in detail
    # Must be empty on both sides: a refused create writes no row, and a row left over
    # from a previous run would change what the dialog draws.
    facts["server_rows"] = len(api_get(session, "/api/mcp/servers/", timeout=60))

    # ---- the numbers the picture cannot show --------------------------------
    tools_py = _installed_tools_py(session.home)
    facts["tools_py"] = str(tools_py) if tools_py else None
    if tools_py is None:
        raise RuntimeError(f"no installed tools.py under {session.home}")
    measured = _model_facing_specs(tools_py, FIXTURE_MCP_TOOLS)
    facts["discovered_tool_count"] = len(FIXTURE_MCP_TOOLS)
    facts["model_facing_mcp_tool_count"] = measured["count"]
    facts["model_facing_mcp_tool_names"] = measured["names"]
    facts["has_visibility_filter"] = measured["has_visibility_filter"]

    # ---- the picture --------------------------------------------------------
    init = seed_init_script(
        type("A", (), {"access_token": session.access_token,
                       "refresh_token": session.refresh_token})(),
        [],
        # The composer renders the MCP pill only while the chat's MCP preference is on
        # (`mcpEnabledForChat`), and the plus-menu item that turns it on is disabled
        # until a tool-capable model is loaded. Seeding the preference key the store
        # itself persists (CHAT_MCP_ENABLED_KEY) reaches the same dialog without
        # loading weights, and seeds identically on both sides.
        extra_local_storage={"unsloth_chat_mcp_enabled": "true"},
    )
    shots: list[Path] = []
    async with open_chat(session.base_url, init_scripts=[init],
                         viewport=VIEWPORT, headless=True) as sp:
        page = sp.page
        # The pill's own glyph is a nested role=button that turns MCP OFF, so the click
        # lands on the label span instead; a click on the glyph never opens the menu.
        pill = page.locator('button[data-pill-label="MCP"]').first
        await pill.wait_for(state="visible", timeout=60_000)
        manage = page.get_by_role("menuitem", name="Manage MCP servers").first
        for attempt in range(6):
            await pill.scroll_into_view_if_needed()
            await pill.locator("span", has_text=re.compile(r"^MCP$")).first.click()
            try:
                await manage.wait_for(state="visible", timeout=4_000)
                break
            except Exception:  # noqa: BLE001 -- Radix loses races with a background refresh
                if attempt == 5:
                    raise
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(1_000)
        await manage.click()

        dialog = page.get_by_role("dialog").filter(has_text="MCP Servers").first
        await dialog.wait_for(state="visible", timeout=30_000)
        facts["dialog_title"] = (
            await dialog.get_by_role("heading").first.inner_text()).strip()
        empty_state = dialog.get_by_text("No MCP servers configured yet.")
        facts["dialog_empty_state"] = bool(await empty_state.count())
        await dialog.get_by_role("button", name="Add server").first.click()

        await _fill(page, "#mcp-display-name", display_name)
        await _fill(page, "#mcp-url", command)
        facts["command_typed"] = await page.locator("#mcp-url").first.input_value()

        await dialog.get_by_role("button", name="Test connection").first.click()
        toast = page.locator(TOAST).first
        await toast.wait_for(state="visible", timeout=30_000)
        # Sonner expires a toast after 5 s but pauses that timer while the pointer is
        # over it, so the hover is what keeps the message on screen for both shots.
        await toast.hover()
        await page.wait_for_timeout(1_200)
        facts["toast_count"] = await page.locator(TOAST).count()
        facts["toast_title"] = " ".join(
            (await toast.locator("[data-title]").first.inner_text()).split())
        facts["toast_description"] = " ".join(
            (await toast.locator("[data-description]").first.inner_text()).split())
        box = await toast.bounding_box()
        facts["toast_box"] = {k: round(v) for k, v in box.items()} if box else None

        shot = out_dir / f"{label.lower()}_mcp_dialog_toast.png"
        await page.screenshot(path=str(shot))
        shots.append(shot)
        corner = out_dir / f"{label.lower()}_toast_corner.png"
        await page.screenshot(path=str(corner), clip=TOAST_CLIP)
        shots.append(corner)

    # The toast is the surface; the API reading is the proof. They must agree, or one of
    # the two is not describing the refusal that was photographed.
    if facts["toast_description"] != facts["stdio_gate_test_detail"]:
        raise RuntimeError(
            "toast description and the 400 detail disagree:\n"
            f"  toast: {facts['toast_description']!r}\n"
            f"  api  : {facts['stdio_gate_test_detail']!r}"
        )

    print(f"[{label}] {json.dumps(facts)[:1600]}", flush=True)
    return shots, facts


if __name__ == "__main__":
    import argparse

    from pr_ui_scenes._common import studio_session

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default="AFTER")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    s = studio_session(a.url, a.home, a.password)
    print(asyncio.run(drive(s, a.out, a.label)))

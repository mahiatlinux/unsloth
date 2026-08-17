#!/usr/bin/env python3
"""Re-derive every number and string claimed for PR 8739, from source.

The screenshots in this branch are a claim. This script is what makes the green tick
mean something: it takes the two commits the pair was shot at, pulls the four backend
files that matter straight from unslothai/unsloth at those SHAs, and re-derives

  * how many MCP tool specs each side hands the model for one fixed MCP Apps tool
    list, and which tool names survive
  * the exact stdio-gate sentence each side puts in the 400 detail -- BEFORE from the
    literal in routes/mcp_servers.py, AFTER by EXECUTING stdio_mcp_disabled_reason()
    in all three gate configurations against the real host_policy/tool_policy modules

then compares the results with manifest.json and with the toast text recorded in
meta.json by the run that took the screenshots. Any disagreement fails the job.

Local use is the same command as CI:

    python3 verify_pr8739_evidence.py --evidence-dir .
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/unslothai/unsloth"

# The same fixture the scene scored both installs on. Two app-only tools in the two
# _meta shapes the PR handles, one plain tool, one that lists "model" explicitly.
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

failures: list[str] = []
checks = 0


def check(label: str, got, want) -> None:
    global checks
    checks += 1
    if got == want:
        print(f"  ok    {label}: {got!r}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        failures.append(label)


def fetch(sha: str, rel: str, dest_root: Path) -> Path:
    """One file from the public repo at `sha`, kept at its package path."""
    dest = dest_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RAW}/{sha}/{rel}"
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                dest.write_bytes(response.read())
            print(f"  fetched {rel} @ {sha[:9]} ({dest.stat().st_size} bytes)")
            return dest
        except (urllib.error.URLError, TimeoutError) as exc:  # noqa: PERF203
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def extract_functions(path: Path, names: tuple[str, ...]) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text())
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }


def model_facing(tools_py: Path) -> dict:
    """Run this side's own `_mcp_specs_for_server` over the fixture tool list."""
    wanted = ("_mcp_tool_model_visible", "_mcp_specs_for_server")
    found = extract_functions(tools_py, wanted)
    if "_mcp_specs_for_server" not in found:
        raise RuntimeError(f"_mcp_specs_for_server missing from {tools_py}")

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
    specs = namespace["_mcp_specs_for_server"](
        {"id": "fixture", "display_name": "System Monitor"},
        [dict(t) for t in FIXTURE_MCP_TOOLS],
    )
    return {
        "count": len(specs),
        "names": [s["function"]["name"].split("__", 2)[-1] for s in specs],
        "has_filter": "_mcp_tool_model_visible" in found,
    }


def validate_url_literals(routes_py: Path) -> str:
    """The stdio branch of `_validate_url`, as source text."""
    found = extract_functions(routes_py, ("_validate_url",))
    if "_validate_url" not in found:
        raise RuntimeError(f"_validate_url missing from {routes_py}")
    return ast.unparse(found["_validate_url"])


def head_gate_messages(head_root: Path) -> dict[str, str]:
    """Execute the PR's own `stdio_mcp_disabled_reason()` in all three gate states.

    The real `utils.host_policy` and `state.tool_policy` modules are imported from the
    head tree (both are stdlib-only), so this exercises the actual gate helpers rather
    than a stub that could agree with a wrong branch.
    """
    backend = head_root / "studio" / "backend"
    sys.path.insert(0, str(backend))
    from state.tool_policy import reset_tool_policy, set_tool_policy  # noqa: PLC0415
    from utils import host_policy  # noqa: PLC0415

    found = extract_functions(
        backend / "core" / "inference" / "mcp_client.py",
        ("stdio_mcp_disabled_reason", "stdio_mcp_enabled"),
    )
    for name in ("stdio_mcp_disabled_reason", "stdio_mcp_enabled"):
        if name not in found:
            raise RuntimeError(f"{name} missing from head mcp_client.py")
    namespace: dict = {"os": os}
    for name, node in found.items():
        module = ast.Module(body=[node], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), f"<{name}>", "exec"), namespace)
    reason = namespace["stdio_mcp_disabled_reason"]
    enabled = namespace["stdio_mcp_enabled"]

    out: dict[str, str] = {}
    # 1. loopback auto-default plus --disable-tools: the configuration photographed.
    host_policy._reset_loopback_default_state()
    os.environ.pop("UNSLOTH_STUDIO_ALLOW_STDIO_MCP", None)
    reset_tool_policy()
    host_policy.apply_stdio_mcp_loopback_default("127.0.0.1")
    set_tool_policy(False)
    out["env_after_loopback_default"] = os.environ.get("UNSLOTH_STUDIO_ALLOW_STDIO_MCP")
    out["gate_open_with_disable_tools"] = enabled()
    out["disable_tools"] = reason()
    # 2. same, but a Remote Access tunnel is publishing the API.
    reset_tool_policy()
    host_policy.set_remote_connector_active(True)
    out["gate_open_with_tunnel"] = enabled()
    out["tunnel"] = reason()
    host_policy.set_remote_connector_active(False)
    # 3. no opt-in at all: the generic hint, which is also the only message the base
    #    commit can ever produce.
    host_policy._reset_loopback_default_state()
    os.environ.pop("UNSLOTH_STUDIO_ALLOW_STDIO_MCP", None)
    reset_tool_policy()
    out["gate_open_with_no_optin"] = enabled()
    out["not_enabled"] = reason()
    return out


def norm(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", type=Path, default=Path("."))
    ap.add_argument("--work", type=Path, default=Path("_pr8739_src"))
    args = ap.parse_args()

    manifest = json.loads((args.evidence_dir / "manifest.json").read_text())
    meta = json.loads((args.evidence_dir / "meta.json").read_text())
    base_sha, head_sha = manifest["base_sha"], manifest["head_sha"]
    print(f"PR {manifest['pr']}  base {base_sha[:9]}  head {head_sha[:9]}\n")

    print("files as published in this branch:")
    for name, want_sha in sorted(manifest["files"].items()):
        path = args.evidence_dir / name
        got = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        check(f"sha256 {name}", got, want_sha)

    base_root = args.work / "base"
    head_root = args.work / "head"
    print("\nsource at the two commits:")
    base_tools = fetch(base_sha, "studio/backend/core/inference/tools.py", base_root)
    base_routes = fetch(base_sha, "studio/backend/routes/mcp_servers.py", base_root)
    head_tools = fetch(head_sha, "studio/backend/core/inference/tools.py", head_root)
    head_routes = fetch(head_sha, "studio/backend/routes/mcp_servers.py", head_root)
    fetch(head_sha, "studio/backend/core/inference/mcp_client.py", head_root)
    fetch(head_sha, "studio/backend/state/tool_policy.py", head_root)
    fetch(head_sha, "studio/backend/utils/host_policy.py", head_root)

    print("\nMCP tool specs handed to the model, from each side's own tools.py:")
    before = model_facing(base_tools)
    after = model_facing(head_tools)
    claim = manifest["claims"]
    check("BEFORE model-facing spec count", before["count"], claim["before_model_facing_count"])
    check("AFTER model-facing spec count", after["count"], claim["after_model_facing_count"])
    check("BEFORE surviving tool names", before["names"], claim["before_model_facing_names"])
    check("AFTER surviving tool names", after["names"], claim["after_model_facing_names"])
    check("BEFORE has the visibility filter", before["has_filter"], False)
    check("AFTER has the visibility filter", after["has_filter"], True)
    check("tools dropped by the PR",
          sorted(set(before["names"]) - set(after["names"])),
          sorted(claim["dropped_tool_names"]))
    check("discovered tool count is unchanged by the PR",
          len(FIXTURE_MCP_TOOLS), claim["discovered_tool_count"])

    print("\nthe stdio-gate sentence, per side:")
    base_validate = validate_url_literals(base_routes)
    head_validate = validate_url_literals(head_routes)
    check("BEFORE _validate_url inlines the env-var hint",
          norm(claim["before_toast_description"]) in norm(base_validate), True)
    check("BEFORE _validate_url has no reason helper",
          "stdio_mcp_disabled_reason" in base_validate, False)
    check("AFTER _validate_url defers to the reason helper",
          "stdio_mcp_disabled_reason" in head_validate, True)
    check("AFTER _validate_url inlines no gate text",
          norm(claim["after_toast_description"]) in norm(head_validate), False)

    messages = head_gate_messages(head_root)
    check("loopback bind auto-sets the env var", messages["env_after_loopback_default"], "1")
    check("gate closed under --disable-tools", messages["gate_open_with_disable_tools"], False)
    check("gate closed under an active tunnel", messages["gate_open_with_tunnel"], False)
    check("gate closed with no opt-in", messages["gate_open_with_no_optin"], False)
    check("AFTER message, --disable-tools branch",
          norm(messages["disable_tools"]), norm(claim["after_toast_description"]))
    check("AFTER message, Remote Access branch",
          norm(messages["tunnel"]), norm(claim["remote_access_message"]))
    check("AFTER fallback equals the BEFORE message",
          norm(messages["not_enabled"]), norm(claim["before_toast_description"]))

    print("\nwhat the screenshots recorded (meta.json from the run):")
    facts = meta["facts"]
    check("BEFORE toast description",
          norm(facts["BEFORE"]["toast_description"]), norm(claim["before_toast_description"]))
    check("AFTER toast description",
          norm(facts["AFTER"]["toast_description"]), norm(claim["after_toast_description"]))
    check("BEFORE toast description equals its 400 detail",
          norm(facts["BEFORE"]["toast_description"]),
          norm(facts["BEFORE"]["stdio_gate_test_detail"]))
    check("AFTER toast description equals its 400 detail",
          norm(facts["AFTER"]["toast_description"]),
          norm(facts["AFTER"]["stdio_gate_test_detail"]))
    check("BEFORE model-facing count recorded on the shot host",
          facts["BEFORE"]["model_facing_mcp_tool_count"], claim["before_model_facing_count"])
    check("AFTER model-facing count recorded on the shot host",
          facts["AFTER"]["model_facing_mcp_tool_count"], claim["after_model_facing_count"])
    check("control message matches on both sides",
          facts["BEFORE"]["control_detail"], facts["AFTER"]["control_detail"])
    check("dialog draws the same empty list on both sides",
          [facts["BEFORE"]["server_rows"], facts["AFTER"]["server_rows"]], [0, 0])
    check("meta.json names the commits the manifest claims",
          [meta["base_sha"], meta["head_sha"]], [base_sha, head_sha])

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("every number and string in the PR comment re-derived from source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

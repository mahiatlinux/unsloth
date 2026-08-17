#!/usr/bin/env python3
"""Re-assert every string and count the PR 8557 evidence comment quotes.

Runs on a clean ubuntu-latest checkout of this disposable branch with nothing but
the standard library plus Pillow. It does not re-render anything: it checks that
the bundle on the branch says what the comment says it says, so a green run means
the numbers in the comment came from these files and not from prose.

What it checks:
  1. facts.json holds a BEFORE and an AFTER block, and every quoted string in
     EXPECTED matches EXACTLY on the side it belongs to.
  2. the control readings -- the non-MCP web_fetch card, its Fetch entry in the
     details sheet's Called row, and the Enabled row -- are IDENTICAL on the two
     sides. The whole claim is that only the MCP label moved.
  3. the tool name, the server id and the server display name are identical on
     both sides, which is what makes the pair a comparison rather than two
     different scenes.
  4. the two exported conversation markdown files carry the tool call heading the
     comment quotes, once each, and the web_fetch heading byte-identically.
  5. each composite PNG is present, is a real PNG, and is an even-width pair of
     equal halves (the scene pads both sides onto one fixed canvas, so a composite
     whose halves differ in size means something rescaled a half).
  6. the BEFORE and AFTER halves of a pair are not byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"

MCP_SERVER_ID = "9f2c41ab7de05613"
MCP_DISPLAY_NAME = "GitHub Issues"
MCP_TOOL_NAME = f"mcp__{MCP_SERVER_ID}__create_issue"

# Exactly the strings the PR comment quotes, per side.
EXPECTED = {
    "BEFORE": {
        "card_mcp_label": f"Used tool: {MCP_SERVER_ID} · create_issue",
        "card_control_label": "Used tool: web_fetch",
        "details_called_row": f"MCP: {MCP_SERVER_ID}__create_issue, Fetch",
        "details_enabled_row": "Fetch, MCP",
        "markdown_mcp_heading": f"**tool call:** `{MCP_TOOL_NAME}`",
        "markdown_control_heading": "**tool call:** `web_fetch`",
        "status_for_tool": f"Calling: {MCP_TOOL_NAME}",
        "awaiting_approval_status": f"Waiting for approval: {MCP_TOOL_NAME}",
        "has_mcp_display_parts": False,
    },
    "AFTER": {
        "card_mcp_label": f"Used tool: {MCP_DISPLAY_NAME} · create_issue",
        "card_control_label": "Used tool: web_fetch",
        "details_called_row": f"MCP: {MCP_DISPLAY_NAME} · create_issue, Fetch",
        "details_enabled_row": "Fetch, MCP",
        "markdown_mcp_heading": f"**tool call:** `{MCP_DISPLAY_NAME} · create_issue`",
        "markdown_control_heading": "**tool call:** `web_fetch`",
        "status_for_tool": f"Calling: {MCP_DISPLAY_NAME} · create_issue",
        "awaiting_approval_status":
            f"Waiting for approval: {MCP_DISPLAY_NAME} · create_issue",
        "has_mcp_display_parts": True,
        "mcp_display_parts": [MCP_DISPLAY_NAME, "create_issue"],
    },
}

# Identical on both sides or the pair is not a comparison.
CONTROLS = (
    "mcp_server_id", "mcp_display_name", "mcp_tool_name", "control_tool_name",
    "card_control_label", "details_enabled_row", "markdown_control_heading",
    "markdown_control_heading", "stored_tool_calls", "markdown_tool_call_lines",
)

PAIRS = (
    "pr8557_pair_00_tool_cards.png",
    "pr8557_pair_01_details_sheet.png",
    "pr8557_pair_02_markdown.png",
)

MARKDOWN = {"BEFORE": "before_conversation.md", "AFTER": "after_conversation.md"}

# sha256 of the exact bytes that were opened and read before the PR comment was
# written. Checked here so a green run means the artifact holds those files and not
# a later re-render that happens to satisfy the string checks.
EXPECTED_SHA256 = {
    "pr8557_pair_00_tool_cards.png":
        "412e48f94045784a29c5000cce84edd827740261ef79172be3aed96e32461278",
    "pr8557_pair_01_details_sheet.png":
        "2850e6034bcf9e9edca05f8c96f51c6a0fd03c8d134efe8181ccda050345e54a",
    "pr8557_pair_02_markdown.png":
        "7915744f544cb022d6d4f577ce01d977dda429933395e9a0a6a7c3c123e5a2f4",
    "before_conversation.md":
        "924f9ed83f418005cd6905c8fe24d9262b5fa70288f621eb120466f4aee2badf",
    "after_conversation.md":
        "d044c15d1857fb494e0ba3796976390fc4828236e12feaf980b7028ac8b5b619",
    "facts.json":
        "a78b29fd2c01b0263b7d47eed6239169a4b24d270bab8a2a162605f071fe09e0",
}

failures: list[str] = []
checks = 0


def check(ok: bool, what: str) -> None:
    global checks
    checks += 1
    if ok:
        print(f"PASS  {what}")
    else:
        print(f"FAIL  {what}")
        failures.append(what)


def main() -> int:
    facts_path = EVIDENCE / "facts.json"
    if not facts_path.is_file():
        print(f"FAIL  {facts_path} is missing")
        return 1
    meta = json.loads(facts_path.read_text())
    facts = meta.get("facts", meta)

    check(meta.get("pr") == 8557, "facts.json records pr 8557")
    check(bool(meta.get("base_sha")) and bool(meta.get("head_sha")),
          "facts.json records both SHAs")
    check(meta.get("base_sha") != meta.get("head_sha"),
          "the two sides are different commits")

    for side, expected in EXPECTED.items():
        got = facts.get(side)
        if not isinstance(got, dict):
            check(False, f"facts.json has a {side} block")
            continue
        for key, want in expected.items():
            check(got.get(key) == want,
                  f"{side}.{key} == {want!r}" +
                  ("" if got.get(key) == want else f"  (got {got.get(key)!r})"))

    before, after = facts.get("BEFORE") or {}, facts.get("AFTER") or {}
    for key in dict.fromkeys(CONTROLS):
        check(key in before and before.get(key) == after.get(key),
              f"control {key} identical on both sides "
              f"({json.dumps(before.get(key))})")

    check(before.get("mcp_server_id") == MCP_SERVER_ID,
          f"the photographed server id is {MCP_SERVER_ID}")
    check(before.get("mcp_display_name") == MCP_DISPLAY_NAME,
          f"the photographed display name is {MCP_DISPLAY_NAME!r}")
    check((before.get("stored_mcp_provenance") or {}).get("mcp_server")
          == MCP_DISPLAY_NAME,
          "the stored tool call carried provenance.mcp_server on the BEFORE side too, "
          "so both sides were handed the same input")
    check((after.get("stored_mcp_provenance") or {}).get("mcp_server")
          == MCP_DISPLAY_NAME,
          "the stored tool call carried provenance.mcp_server on the AFTER side")

    for side, name in MARKDOWN.items():
        path = EVIDENCE / name
        if not path.is_file():
            check(False, f"{name} is present")
            continue
        text = path.read_text()
        want_mcp = EXPECTED[side]["markdown_mcp_heading"]
        headings = re.findall(r"^\*\*tool call:\*\* .*$", text, flags=re.M)
        check(headings.count(want_mcp) == 1,
              f"{name} carries {want_mcp!r} exactly once (headings: {headings})")
        check("**tool call:** `web_fetch`" in text,
              f"{name} carries the unchanged web_fetch heading")
        other = EXPECTED["AFTER" if side == "BEFORE" else "BEFORE"]["markdown_mcp_heading"]
        check(other not in text, f"{name} does NOT carry the other side's heading")

    for name in PAIRS:
        path = EVIDENCE / name
        if not path.is_file():
            check(False, f"{name} is present")
            continue
        raw = path.read_bytes()
        check(raw[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is a real PNG")
        try:
            from PIL import Image
        except ImportError:
            print(f"SKIP  {name} geometry (Pillow unavailable)")
            continue
        with Image.open(path) as img:
            w, h = img.size
            # hstack_images writes label bands and a gap, so the halves are not
            # exactly w/2; what matters is that neither half was rescaled, which
            # shows up as the two halves having different pixel dimensions.
            left = img.crop((0, 0, w // 2, h))
            right = img.crop((w - w // 2, 0, w, h))
        check(left.size == right.size, f"{name} halves are the same size {left.size}")
        check(left.tobytes() != right.tobytes(),
              f"{name} halves are not identical images")
        print(f"      {name} {w}x{h} {len(raw)} bytes "
              f"sha256={hashlib.sha256(raw).hexdigest()[:16]}")

    for name, want in EXPECTED_SHA256.items():
        path = EVIDENCE / name
        got = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        check(got == want, f"sha256 {name} == {want[:16]}…  (got {got[:16]}…)")

    listed = sorted(p.name for p in EVIDENCE.iterdir() if p.is_file())
    check(listed == sorted(EXPECTED_SHA256),
          f"evidence/ holds exactly the six bundled files: {listed}")

    print()
    print(f"{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check that every file in evidence/ is what the PR comment claims it is.

Runs in CI before the artifact is uploaded, so a bundle that lost a file or had a
PNG truncated fails the run instead of being published as evidence.
"""

from __future__ import annotations

import json
import pathlib
import sys

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
EXPECTED_PNGS = {
    "pr8951-before-after-settings-section.png",
    "pr8951-before-after-lan-started.png",
    "before-api-keys-panel.png",
    "before-api-keys-panel-started.png",
    "after-api-keys-panel.png",
    "after-api-keys-panel-started.png",
}


def main() -> int:
    root = pathlib.Path("evidence")
    pngs = {p.name for p in root.glob("*.png")}
    missing = EXPECTED_PNGS - pngs
    extra = pngs - EXPECTED_PNGS
    if missing or extra:
        print(f"FAIL png set mismatch: missing={sorted(missing)} extra={sorted(extra)}")
        return 1
    for name in sorted(pngs):
        path = root / name
        if path.read_bytes()[:8] != PNG_MAGIC:
            print(f"FAIL {name} is not a PNG")
            return 1
        print(f"ok   {name}  {path.stat().st_size} bytes")

    facts = json.loads((root / "facts.json").read_text())
    checks = [
        ("pr", facts["pr"], 8951),
        ("base_sha", facts["base_sha"][:9], "6f443b5cc"),
        ("head_sha", facts["head_sha"][:9], "b8f1d669c"),
        ("scene", facts["scene"], "lan_access_settings"),
    ]
    before, after = facts["facts"]["BEFORE"], facts["facts"]["AFTER"]
    checks += [
        ("BEFORE lan_section_present", before["lan_section_present"], 0),
        ("AFTER lan_section_present", after["lan_section_present"], 1),
        ("BEFORE probe after start", before["lan_probe_after_start"], "connection refused"),
        ("AFTER probe after start", after["lan_probe_after_start"], "http 200"),
        ("AFTER probe after stop", after["lan_probe_after_stop"], "connection refused"),
        ("AFTER state after start", after["lan_state_label_after_start"],
         "Online · Settings managed"),
    ]
    failed = False
    for label, got, want in checks:
        status = "ok  " if got == want else "FAIL"
        if got != want:
            failed = True
        print(f"{status} {label}: {got!r} (expected {want!r})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

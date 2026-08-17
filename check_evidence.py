#!/usr/bin/env python3
"""Check the packaged evidence against what the PR 8879 comment claims.

Every assertion here restates a sentence from that comment, so a file swapped for
something else, or a fact table edited after the fact, fails the run instead of shipping
an artifact that quietly disagrees with the text beside it.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent / "evidence"
DATE_ROW = "Tell the model today's date"
CONTROL_ROWS = [
    "Collapse Thinking by default",
    "Show model disclaimer",
    "Show response model",
    "Auto-title new chats",
    "Sloth in greeting",
]


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path.name} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def main() -> int:
    expected = [
        "chat-defaults-before-after.png",
        "before_chat_defaults.png",
        "after_chat_defaults.png",
        "facts.json",
    ]
    for name in expected:
        path = EVIDENCE / name
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"missing or empty: {name}")
    extra = sorted(p.name for p in EVIDENCE.iterdir() if p.name not in expected)
    if extra:
        raise SystemExit(f"unlisted files would ship in the artifact: {extra}")

    # hstack_images equalises heights by SCALING, so halves of different sizes mean one
    # was blown up and the pair looks retouched. Both are padded onto one canvas.
    for name in ("before_chat_defaults.png", "after_chat_defaults.png"):
        size = png_size(EVIDENCE / name)
        print(f"{name} {size[0]}x{size[1]}")
        if size != (690, 452):
            raise SystemExit(f"{name} is {size}, expected the shared 690x452 canvas")
    composite = png_size(EVIDENCE / "chat-defaults-before-after.png")
    print(f"chat-defaults-before-after.png {composite[0]}x{composite[1]}")
    if composite[0] < 1300 or composite[1] < 460:
        raise SystemExit(f"composite is {composite}, too small to be the labelled pair")

    facts = json.loads((EVIDENCE / "facts.json").read_text())
    if not facts["base_sha"].startswith("203007d19"):
        raise SystemExit(f"base is {facts['base_sha']}, not the PR's merge base")
    if not facts["head_sha"].startswith("b783353630"):
        raise SystemExit(f"head is {facts['head_sha']}")
    before, after = facts["facts"]["BEFORE"], facts["facts"]["AFTER"]

    if before["chat_defaults_row_count"] != 5 or after["chat_defaults_row_count"] != 6:
        raise SystemExit("Chat defaults row counts are not 5 -> 6")
    if before["chat_defaults_rows"] != CONTROL_ROWS:
        raise SystemExit(f"base rows are {before['chat_defaults_rows']}")
    if after["chat_defaults_rows"] != [DATE_ROW, *CONTROL_ROWS]:
        raise SystemExit(f"head rows are {after['chat_defaults_rows']}")
    if after["date_switch_aria_checked"] != "true":
        raise SystemExit("the new row's Switch is not on by default")
    if before["settings_api"] != "HTTP 404":
        raise SystemExit(f"base settings route answered {before['settings_api']}")
    if after["settings_api"] != {"enabled": True, "default_enabled": True}:
        raise SystemExit(f"head settings route answered {after['settings_api']}")

    if before["proxied_system_prompt"] != "Be terse.":
        raise SystemExit(f"base proxied {before['proxied_system_prompt']!r}")
    if not after["proxied_system_prompt"].startswith("The current date is "):
        raise SystemExit(f"head proxied {after['proxied_system_prompt']!r}")
    if not after["proxied_system_prompt"].endswith("\n\nBe terse."):
        raise SystemExit("the date line does not sit ahead of the user's own prompt")
    if after["proxied_system_prompt_setting_off"] != "Be terse.":
        raise SystemExit("turning the setting off did not remove the date line")

    print("every claim in the comment holds against the packaged files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

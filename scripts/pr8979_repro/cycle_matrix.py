#!/usr/bin/env python3
"""Run the module-scope cycle matrix on two checkouts and assert the outcome.

The claim under test for PR 8979 is not "the app looks different". It is which import
shapes survive module evaluation. Six cells, three per side:

  shipped imports, entered at the chat barrel   both sides render
  general-tab reads the key via the barrel      both sides throw, so the PR does not
                                                protect this shape
  the store itself pulled into the cycle        base throws, head renders, which is the
                                                one thing the PR changes

A cell that deviates fails the run. A matrix where nothing differs between the sides
would mean the PR changes nothing even under perturbation, and is also a failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).with_name("cycle_probe.py")

# (entry, patch, base_renders, head_renders)
CELLS = [
    ("barrel-first", "none", True, True),
    ("barrel-first", "general-tab-via-barrel", False, False),
    ("store-first", "store-in-cycle", False, True),
]


def reset(checkout: Path) -> None:
    subprocess.run(["git", "checkout", "--", "studio/frontend/src"], cwd=checkout, check=True)
    for name in ("smoke-cycle.html", "smoke-cycle-main.tsx"):
        (checkout / "studio" / "frontend" / name).unlink(missing_ok=True)


def probe(checkout: Path, side: str, entry: str, patch: str, out_dir: Path) -> dict:
    reset(checkout)
    label = f"{side}/{entry}/{patch}"
    proc = subprocess.run(
        [sys.executable, str(PROBE),
         "--frontend", str(checkout / "studio" / "frontend"),
         "--entry", entry, "--patch", patch, "--label", label,
         "--log", str(out_dir / f"vite_{side}_{entry}_{patch}.log"),
         "--screenshot", str(out_dir / f"{side}_{entry}_{patch}.png")],
        text=True, capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    reset(checkout)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("PROBE ")), None)
    if line is None:
        raise SystemExit(f"{label}: probe produced no result (rc={proc.returncode})")
    return json.loads(line[len("PROBE "):])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True, help="checkout at the merge base")
    ap.add_argument("--head", type=Path, required=True, help="checkout at the PR head")
    ap.add_argument("--out-dir", type=Path, default=Path("cycle-artifacts"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    rows: list[dict] = []
    for entry, patch, base_expected, head_expected in CELLS:
        for side, checkout, expected in (("base", args.base, base_expected),
                                         ("head", args.head, head_expected)):
            result = probe(checkout, side, entry, patch, args.out_dir)
            got = bool(result["rendered"])
            rows.append({**result, "side": side, "expected_rendered": expected})
            verdict = "ok" if got == expected else "MISMATCH"
            if got != expected:
                failures.append(
                    f"{side}/{entry}/{patch}: expected rendered={expected}, got {got} "
                    f"(tdz={result['tdz'][:80]!r})"
                )
            print(f"  {side:4} {entry:12} {patch:22} rendered={got!s:5} {verdict}", flush=True)

    (args.out_dir / "matrix.json").write_text(json.dumps(rows, indent=2, sort_keys=True))

    moved = [r for r in CELLS if r[2] != r[3]]
    print(f"\ncells where the two sides differ: {len(moved)}")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nmatrix matched expectations on every cell")
    return 0


if __name__ == "__main__":
    sys.exit(main())

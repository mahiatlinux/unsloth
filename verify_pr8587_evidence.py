#!/usr/bin/env python3
"""Re-assert, in CI, every number quoted in the PR 8587 evidence comment.

The comment claims specific strings and file digests. This script fails unless the files on
this branch still say exactly that, so a green run means the comment and the artifact agree
rather than merely that an upload step succeeded.

Three groups of checks:

1. every PNG's sha256 and byte length match what pr8587_facts.json recorded on the box that
   took them, so the artifact cannot drift from the images the comment inlines;
2. the per-side facts equal the values quoted in the comment, including the controls that
   have to MATCH across the two sides (a pair whose sides disagree on what context 1 loaded
   proves nothing about memory);
3. the two sides' source shots are not byte-identical, which is the failure mode that looks
   most like a clean run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FACTS_FILE = HERE / "pr8587_facts.json"

# Quoted in the comment, per side.
QUOTED = {
    "BEFORE": {
        "backend_last_local_model": "http 404",
        "ctx2_toast_title": "Loading a model…",
        "ctx2_toast_model": "unsloth/Qwen3-0.6B-GGUF (Q2_K)",
        "ctx2_auto_loaded_model": "unsloth/Qwen3-0.6B-GGUF",
        "ctx2_auto_loaded_variant": "Q2_K",
        "ctx2_auto_loaded_is_remembered": False,
    },
    "AFTER": {
        "ctx2_toast_title": "Loading last used model…",
        "ctx2_toast_model": "unsloth/Qwen3-1.7B-GGUF (Q4_K_M)",
        "ctx2_auto_loaded_model": "unsloth/Qwen3-1.7B-GGUF",
        "ctx2_auto_loaded_variant": "Q4_K_M",
        "ctx2_auto_loaded_is_remembered": True,
    },
}

# The AFTER backend setting is a record, not a string: the id/kind/variant are quoted, the
# timestamp is not (it is the wall clock of the load).
AFTER_BACKEND_RECORD = {
    "id": "unsloth/Qwen3-1.7B-GGUF",
    "kind": "gguf",
    "gguf_variant": "Q4_K_M",
}

# Must be EQUAL on both sides, or the two halves are not comparable.
CONTROLS = (
    "ctx1_picked_model",
    "ctx1_loaded_model",
    "ctx1_loaded_variant",
    "ctx1_picker_trigger_text",
    "ctx2_localstorage_at_boot",
    "resident_at_start",
    "resident_before_ctx2",
    "cached_gguf_repos",
)


def _fail(problems: list[str], message: str) -> None:
    problems.append(message)
    print(f"FAIL  {message}")


def main() -> int:
    problems: list[str] = []
    facts = json.loads(FACTS_FILE.read_text())
    sides = facts["facts"]

    print(f"PR {facts['pr']}  base {facts['base_sha'][:9]}  head {facts['head_sha'][:9]}")
    print(f"scene {facts['scene']}\n")

    for name, meta in sorted(facts["files"].items()):
        path = HERE / name
        if not path.exists():
            _fail(problems, f"{name} is missing from the branch")
            continue
        blob = path.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if len(blob) != meta["bytes"] or digest != meta["sha256"]:
            _fail(problems, f"{name} changed: {len(blob)} B {digest[:16]} != "
                            f"{meta['bytes']} B {meta['sha256'][:16]}")
        else:
            print(f"ok    {name}  {len(blob)} B  sha256 {digest[:16]}…")

    for side, quoted in QUOTED.items():
        for key, want in quoted.items():
            got = sides[side].get(key)
            if got != want:
                _fail(problems, f"{side}.{key}: {got!r} != quoted {want!r}")
            else:
                print(f"ok    {side}.{key} == {want!r}")

    record = sides["AFTER"].get("backend_last_local_model")
    if not isinstance(record, dict):
        _fail(problems, f"AFTER.backend_last_local_model is not a record: {record!r}")
    else:
        for key, want in AFTER_BACKEND_RECORD.items():
            if record.get(key) != want:
                _fail(problems, f"AFTER.backend_last_local_model.{key}: "
                                f"{record.get(key)!r} != {want!r}")
        if not isinstance(record.get("loaded_at"), int) or record["loaded_at"] <= 0:
            _fail(problems, "AFTER.backend_last_local_model.loaded_at is not an epoch ms int")
        if not problems:
            print(f"ok    AFTER.backend_last_local_model == {json.dumps(record)}")

    # The legacy shadow is still written on BOTH sides -- the PR keeps it as an upgrade
    # fallback -- so the model it names is a control. Only the extra pendingSync marker the
    # new writer adds may differ, and it must be False by the time this is read: a shadow
    # left pending would mean the PUT never confirmed.
    shadows = {side: sides[side].get("ctx1_localstorage_record") for side in ("BEFORE", "AFTER")}
    triples = {side: None if not isinstance(rec, dict) else
               (rec.get("id"), rec.get("kind"), rec.get("ggufVariant"))
               for side, rec in shadows.items()}
    if triples["BEFORE"] != triples["AFTER"]:
        _fail(problems, f"the localStorage shadow names different models: {triples}")
    elif triples["BEFORE"] != ("unsloth/Qwen3-1.7B-GGUF", "gguf", "Q4_K_M"):
        _fail(problems, f"the localStorage shadow is not the picked model: {triples['BEFORE']}")
    else:
        print(f"ok    control localStorage shadow names {triples['BEFORE']} on both sides")
    if "pendingSync" in shadows["BEFORE"]:
        _fail(problems, "the BEFORE writer must not stamp pendingSync")
    elif shadows["AFTER"].get("pendingSync") is not False:
        _fail(problems, f"AFTER pendingSync is {shadows['AFTER'].get('pendingSync')!r}, "
                        "so the backend PUT never confirmed")
    else:
        print("ok    pendingSync absent BEFORE, False AFTER (the PUT confirmed)")

    for key in CONTROLS:
        before, after = sides["BEFORE"].get(key), sides["AFTER"].get(key)
        if before != after:
            _fail(problems, f"control {key} differs between the sides: "
                            f"{before!r} vs {after!r}")
        else:
            print(f"ok    control {key} matches on both sides ({json.dumps(before)[:80]})")

    # The one failure that looks exactly like a successful run.
    for pair in facts["identity_checks"]:
        left, right = HERE / pair["before"], HERE / pair["after"]
        if not (left.exists() and right.exists()):
            _fail(problems, f"cannot compare {pair['before']} with {pair['after']}")
            continue
        if left.read_bytes() == right.read_bytes():
            _fail(problems, f"{pair['before']} and {pair['after']} are BYTE-IDENTICAL")
        else:
            print(f"ok    {pair['before']} differs from {pair['after']}")

    print()
    if problems:
        print(f"{len(problems)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

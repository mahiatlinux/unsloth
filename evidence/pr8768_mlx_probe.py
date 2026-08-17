#!/usr/bin/env python3
"""A/B probe: does this host's resolver call an MLX checkpoint servable?

Run once per side with PYTHONPATH pointing at that side's studio/backend. Prints one
JSON line. The gate under test is the one /v1/models filters its rows through:

  head  local_servable_model(info) -> (is_gguf, quants)  or None
  base  info_has_local_gguf(info) / local_gguf_quants(info)   (no non-GGUF concept)

Nothing is loaded. The point is the classification, on the host that would serve it.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from types import SimpleNamespace

REPO = os.environ["PROBE_REPO"]
SNAPSHOT = os.environ["PROBE_SNAPSHOT"]

out: dict = {
    "side": os.environ.get("PROBE_SIDE", "?"),
    "repo": REPO,
    "platform": f"{platform.system()}/{platform.machine()}",
    "python": platform.python_version(),
}

try:
    import mlx.core as mx
    out["mlx"] = mx.__version__
except Exception as exc:  # noqa: BLE001
    out["mlx"] = f"absent: {type(exc).__name__}"

try:
    from importlib.util import find_spec
    out["mlx_lm_qwen3"] = find_spec("mlx_lm.models.qwen3") is not None
except Exception as exc:  # noqa: BLE001
    out["mlx_lm_qwen3"] = f"error: {exc}"

try:
    from utils.hardware import hardware as hw
    hw.detect_hardware()
    out["device"] = str(getattr(hw.DEVICE, "value", hw.DEVICE))
except Exception as exc:  # noqa: BLE001
    out["device"] = f"error: {type(exc).__name__}: {exc}"

info = SimpleNamespace(id=REPO, model_id=REPO, path=SNAPSHOT, partial=False,
                       display_name=REPO.split("/")[-1])
try:
    import core.inference.local_model_resolver as r
    if hasattr(r, "local_servable_model"):
        verdict = r.local_servable_model(info)
        out["api"] = "local_servable_model"
        out["servable"] = verdict is not None
        out["verdict"] = None if verdict is None else {"is_gguf": verdict[0],
                                                      "quants": list(verdict[1])}
    else:
        # the merge base: the only concept it has is a local GGUF
        out["api"] = "info_has_local_gguf"
        out["servable"] = bool(r.info_has_local_gguf(info))
        out["verdict"] = {"local_gguf_quants": list(r.local_gguf_quants(info) or ())}
    out["resolves"] = r.resolve_local_gguf(REPO, allow_scan=True) is not None
except Exception as exc:  # noqa: BLE001
    out["error"] = f"{type(exc).__name__}: {exc}"

payload = json.dumps(out)
print(payload)
# Written to a file as well: hardware detection prints its own verdict line to stdout,
# so the JSON is never the only thing on it and `tee` produced an unparseable capture.
target = os.environ.get("PROBE_OUT")
if target:
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(payload)
sys.exit(0)

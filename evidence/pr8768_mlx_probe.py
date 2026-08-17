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
    # routes.models imports core.inference, and the resolver imports routes.models back
    # at CALL time to break that cycle. Reaching the resolver first leaves the cycle to
    # be resolved inside the gate, where `_local_weights_entry` swallows the resulting
    # ImportError into None: the first call answered "not servable" while every gate
    # under it was true. The app imports the routers at startup, so mirror that.
    import routes.models  # noqa: F401
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
    # The full index scan, i.e. what /v1/models and the switch resolver actually call.
    resolved = r.resolve_local_gguf(REPO, allow_scan=True)
    out["resolves"] = resolved is not None
    if resolved is not None:
        _load_path, variant, loader_id = resolved
        out["resolved_variant"] = variant
        out["resolved_loader_id"] = loader_id
except Exception as exc:  # noqa: BLE001
    out["error"] = f"{type(exc).__name__}: {exc}"

# When the head withholds the row, say WHICH gate withheld it. `_local_weights_entry`
# swallows every exception into None, so a missing dependency in this probe's own
# environment is indistinguishable from a real refusal until the gates are read one by
# one.
if out.get("servable") is False:
    from pathlib import Path as _Path
    try:
        import core.inference.local_model_resolver as r
        snap = _Path(SNAPSHOT)
        cfg = r._read_json(snap / "config.json") if hasattr(r, "_read_json") else None
        checks = {
            "host_serves_mlx": lambda: r._host_serves_mlx(),
            "host_has_a_non_gguf_backend": lambda: r._host_has_a_non_gguf_backend(),
            "weight_assets_are_complete": lambda: r._weight_assets_are_complete(snap),
            "has_tokenizer_vocabulary": lambda: r._has_tokenizer_vocabulary(snap),
            "is_generative_chat_config": lambda: r._is_generative_chat_config(cfg),
            "quantization_suits_host": lambda: r._quantization_suits_host(cfg),
            "loader_implements_architecture": lambda: r._loader_implements_architecture(cfg),
            "has_a_chat_template": lambda: r._has_a_chat_template(snap, REPO),
            "config_is_servable_here": lambda: r._config_is_servable_here(snap, cfg),
            "local_weights_entry": lambda: r._local_weights_entry(REPO, info) is not None,
        }
        gate_results = {}
        for name, fn in checks.items():
            if not hasattr(r, f"_{name}") and name != "local_weights_entry":
                continue
            try:
                gate_results[name] = fn()
            except Exception as exc:  # noqa: BLE001
                gate_results[name] = f"EXC {type(exc).__name__}: {exc}"
        out["gates"] = gate_results
    except Exception as exc:  # noqa: BLE001
        out["gates"] = f"unavailable: {type(exc).__name__}: {exc}"

payload = json.dumps(out)
print(payload)
# Written to a file as well: hardware detection prints its own verdict line to stdout,
# so the JSON is never the only thing on it and `tee` produced an unparseable capture.
target = os.environ.get("PROBE_OUT")
if target:
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(payload)
sys.exit(0)

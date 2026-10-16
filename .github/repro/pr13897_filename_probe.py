from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "studio" / "backend"))

from utils.models.model_config import _find_local_gguf_by_variant
from core.inference.audio_cpp_models import AudioCppVariant, RepoFile, match_variant


with tempfile.TemporaryDirectory() as raw_root:
    root = Path(raw_root)
    nested = root / "chosen" / "model-Q8_0.gguf"
    nested.parent.mkdir()
    nested.write_bytes(b"GGUF")

    if os.name == "nt":
        selected = _find_local_gguf_by_variant(str(root), r"chosen\model-Q8_0.gguf")
        assert selected == str(nested), (selected, nested)
    else:
        literal = root / r"chosen\model-Q8_0.gguf"
        literal.write_bytes(b"GGUF")
        selected = _find_local_gguf_by_variant(str(root), literal.name)
        assert selected == str(literal), (selected, literal)

with tempfile.TemporaryDirectory() as raw_root:
    root = Path(raw_root)
    upper = root / "Model-Q8_0.gguf"
    lower = root / "model-Q8_0.gguf"
    upper.write_bytes(b"GGUF")
    lower.write_bytes(b"GGUF")
    if not upper.samefile(lower):
        selected = _find_local_gguf_by_variant(str(root), lower.name)
        assert selected == str(lower), (selected, lower)

filename = "model-Q8_0.gguf"
windows_variant = AudioCppVariant(
    "Q8_0",
    (RepoFile(filename),),
    rf"C:\models\english\{filename}",
)
assert match_variant((windows_variant,), f"english/{filename}") is windows_variant

print("PR 13897 filename identity probe passed")

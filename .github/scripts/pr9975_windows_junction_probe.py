# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved.

import subprocess
import tempfile
from pathlib import Path

from hub.services.models import local_inventory
from hub.utils import gguf
from utils.models.model_config import _find_local_gguf_by_variant


def write_gguf(path: Path) -> Path:
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(b"GGUF")
    return path


def custom_rows(*roots: Path):
    rows = []
    for root in roots:
        rows.extend(
            local_inventory._promote_to_custom_source(row)
            for row in local_inventory._scan_custom_folder(root)
        )
    return local_inventory._dedupe_local_models(rows)


with tempfile.TemporaryDirectory() as temporary_directory:
    temporary = Path(temporary_directory)
    root = temporary / "root"
    model = root / "model"
    write_gguf(model / "model-a-Q4_K_M.gguf")
    outside = temporary / "outside" / "Q8_0"
    q8 = write_gguf(outside / "model-a-Q8_0.gguf")
    (outside / "config.json").write_text("{}", encoding = "utf-8")
    junction = model / "Q8_0"
    junction.parent.mkdir(parents = True, exist_ok = True)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check = True,
    )

    variants, _ = gguf.list_local_gguf_variants(str(model), model_root = str(root))
    visible_quants = {variant.quant for variant in variants}
    rows = custom_rows(root, junction)
    if "Q8_0" in visible_quants:
        assert [Path(row.path) for row in rows] == [model]
        resolved = _find_local_gguf_by_variant(
            str(model), "Q8_0", model_root = str(root)
        )
        assert resolved is not None and Path(resolved).samefile(q8)
    else:
        assert {Path(row.path) for row in rows} == {model, junction}

    print(f"PASS junction visibility={sorted(visible_quants)} rows={len(rows)}")

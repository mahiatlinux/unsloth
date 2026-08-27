# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import sys

from PIL import Image, ImageDraw


before_path, after_path, output_path = sys.argv[1:4]
before = Image.open(before_path).convert("RGB")
after = Image.open(after_path).convert("RGB")
width = max(before.width, after.width)
height = max(before.height, after.height)
label_height = 48
canvas = Image.new("RGB", (width * 2, height + label_height), "white")
canvas.paste(before, (0, label_height))
canvas.paste(after, (width, label_height))
draw = ImageDraw.Draw(canvas)
draw.text((20, 15), "BEFORE: merge base 95fd60fa24", fill="black")
draw.text((width + 20, 15), "AFTER: repaired head", fill="black")
canvas.save(output_path)

# Real image recall verification

- Runtime: NVIDIA GeForce RTX 5060 Ti, CUDA 13.0, torch 2.10.0+cu130, diffusers 0.40.0, transformers 5.5.0.
- Model: genuine `segmind/Segmind-Vega` fp16 diffusers pipeline at Hub revision `7714c4363e5856ff974a4f4b068e8691f26d0b40`, stored locally as `<task>/real-image/segmind-vega-sdxl` (3.070 GiB payload).
- Saved settings: the real settings API returned `saved: true` with 512 x 512, 20 steps, guidance 7.0, negative prompt `blurry, low quality`, batch size 1, and runs 1.
- Direct API smoke: the real backend loaded the local SDXL pipeline as bf16 on CUDA and generated one 512 x 512 PNG in 3.354 seconds. The inspected publication copy is `direct-api-teapot.png` (SHA-256 `ad6824fe584041d969422631eaee0026a93d8de2e3c5713514002029140c6e07`).
- Full UI recall: with backend status unloaded and only `{"repoId":"<task>/real-image/segmind-vega-sdxl","kind":"pipeline"}` remembered in browser storage, the first Generate click loaded the real pipeline and generated an image. `ui-checks.json` records the real load and generation request bodies, the exact 512 x 512, 20-step, guidance-7 recipe, and no page errors. Screenshots `41-real-image-remembered.png`, `42-real-image-loading.png`, and `44-real-image-complete.png` capture the initial, load, and completed states. `real-image-demo.webm` records the full flow. The gallery record persisted the exact saved settings and the real file route returned the same PNG bytes as storage.
- Inspected UI output: `ui-recall-teapot-first.png`, 512 x 512 RGB PNG, SHA-256 `7b88deae0fb6c1a5855f8430c6dfe148e1aa3dec352e166e64495f02e3425e9a`. It visibly contains a red ceramic teapot on a sunlit wooden table.

The publication PNG copies had only their embedded recipe text removed because it contained the sandbox model path. Pixel hashes before and after stripping match; `pixel-integrity.json` records the pixel and cleaned-file hashes. Original PNGs with their full recipe metadata remain only under the disposable `<task>/real-image/artifacts/raw` directory.

No model or inference mocks were used. The auth dependency was overridden inside the disposable test API. No source files were changed.

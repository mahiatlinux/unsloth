# Verification

Source commit: `4f8cfdf58`. Base: `02751d21f39b6ab161b24517a1f48f3fce1049a4`.
The committed source exactly matches the implementation snapshot used for these checks.

## Focused tests

Backend, from the repository root:

```sh
python -m pytest studio/backend/tests/test_transcript_gallery.py studio/backend/tests/test_transcript_stream.py studio/backend/tests/test_stt_transcription_cancellation.py studio/backend/tests/test_stt_mtmd_sidecar.py studio/backend/tests/test_stt_sidecar.py studio/backend/tests/test_sd_cpp_backend.py -q
```

272 passed and one Torch-dependent test skipped in the lightweight runtime. The skipped test, `test_transformers_load_inherits_disconnect_before_registration`, subsequently passed in the real Whisper runtime with Torch installed. Total: 273 passing tests.

Frontend, from the repository root:

```sh
node --experimental-strip-types --test studio/frontend/tests/audio-transcript-lifecycle.test.ts studio/frontend/tests/transcript-stream.test.ts studio/frontend/tests/image-model-recall.test.ts studio/frontend/tests/audio-page-policy.test.ts studio/frontend/tests/audio-model-eject.test.ts studio/frontend/tests/audio-stt-download-fallback.test.ts
```

85 passed. Frontend `tsc -b`, `tsc -p tsconfig.test.json`, and Vite production build passed. Ruff passed for changed Python files with the repository configuration. New UI modules had no ESLint findings. The two existing pages had 49 findings in both base and implementation.

Four targeted mutations each failed the relevant test: dropping partial forwarding, ignoring the exact GGUF filename, deleting archived transcripts during Clear all, and omitting persistence before completion. See `mutation-checks.json`.

## UI execution

Automated Playwright interactions exercised the full Studio shell in isolated Chromium contexts. All screenshots were visually inspected; every published recording was checked for playback. Before and after used independent source installs and application homes with matching viewports.

Controlled inference responses exposed short-lived progress, error and history states. These screenshots are separate from the real-model runs identified in the gallery. `ui-checks.json` contains 23 named interaction checks, with additional before/after retention and real-model reports alongside it.

Real runs used an NVIDIA RTX 5060 Ti. Qwen3-ASR 0.6B Q8 and Transformers Whisper Tiny produced partial text before completion. whisper.cpp Tiny returned final text only. Cancellation stopped inference without saving an incomplete result, and subsequent requests succeeded. The browser recording test used Chromium's file-backed test microphone with real MediaRecorder encoding and real Whisper decoding. The speech fixture was the public whisper.cpp JFK recording, repeated for longer inputs.

Real Segmind Vega generation used a local pipeline snapshot. The UI recalled it from an unloaded state and retained the persisted 512x512, 20-step, guidance-7 recipe. Exact GGUF artifact recall was checked with unit tests and controlled browser responses.

## Scope

Native Tauri quit protection was not compiled or executed because the Rust toolchain and GTK/WebKit development dependencies were unavailable. Browser discard confirmations were executed. Representative models were tested, not every catalog model. Pre-push review was skipped at the author's request.

The first image capture helpers had selector and payload-key errors after real generation succeeded; those helpers were corrected without source changes. Final capture and assertions passed. No CI or upstream review result is claimed here.

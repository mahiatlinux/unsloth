# Studio audio and image evidence

Source: `4f8cfdf58`. Base: `02751d21`. 44 original full screenshots, two before/after composites, six recordings, generated images, and executed test reports.

Download this branch and open `index.html` for the interactive gallery. Screenshots labelled REAL use actual model inference. Other states use controlled responses. Desktop: 1600 × 1100; mobile: 390 × 844. Browser confirmations include the complete test browser window.

[Verification commands and scope](verification.md)

## Before and after

![Transcribing](comparison-progress.png)

![Completed transcript](comparison-complete.png)

## Recordings

- [Real Qwen3-ASR streaming](real-qwen-demo.webm)
- [Real Transformers Whisper window updates](real-whisper-demo.webm)
- [Real whisper.cpp final-only decoding](real-whisper-cpp-demo.webm)
- [Browser recording through real Whisper](real-recording-demo.webm)
- [Real image model recall and generation](real-image-demo.webm)
- [Controlled UI states](transcription-demo.webm)

## All full screenshots

<details>
<summary>Before: full Transcribe screen</summary>

![Before: full Transcribe screen](01-before-empty.png)

[Open original](01-before-empty.png)

</details>

<details>
<summary>Before: transcription spinner</summary>

![Before: transcription spinner](02-before-progress.png)

[Open original](02-before-progress.png)

</details>

<details>
<summary>Before: completed transcript without history</summary>

![Before: completed transcript without history](03-before-complete.png)

[Open original](03-before-complete.png)

</details>

<details>
<summary>After: existing Audio Generate screen</summary>

![After: existing Audio Generate screen](04-after-generate.png)

[Open original](04-after-generate.png)

</details>

<details>
<summary>After: Transcribe with empty history</summary>

![After: Transcribe with empty history](05-after-empty.png)

[Open original](05-after-empty.png)

</details>

<details>
<summary>After: live partial transcript, subtle waveform, timer and Cancel</summary>

![After: live partial transcript, subtle waveform, timer and Cancel](06-after-progress.png)

[Open original](06-after-progress.png)

</details>

<details>
<summary>After: completed transcript saved in history</summary>

![After: completed transcript saved in history](07-after-complete.png)

[Open original](07-after-complete.png)

</details>

<details>
<summary>History actions: download, copy, archive and delete</summary>

![History actions: download, copy, archive and delete](08-after-actions.png)

[Open original](08-after-actions.png)

</details>

<details>
<summary>Switch between History and Archived transcripts</summary>

![Switch between History and Archived transcripts](09-after-history-menu.png)

[Open original](09-after-history-menu.png)

</details>

<details>
<summary>Archived transcript remains readable</summary>

![Archived transcript remains readable](10-after-archived.png)

[Open original](10-after-archived.png)

</details>

<details>
<summary>Archived transcript actions include Unarchive</summary>

![Archived transcript actions include Unarchive](11-after-archive-actions.png)

[Open original](11-after-archive-actions.png)

</details>

<details>
<summary>Microphone recording controls</summary>

![Microphone recording controls](12-after-recording.png)

[Open original](12-after-recording.png)

</details>

<details>
<summary>Recorded microphone audio transcribing</summary>

![Recorded microphone audio transcribing](13-after-record-transcribing.png)

[Open original](13-after-record-transcribing.png)

</details>

<details>
<summary>Cancelled transcription with earlier history preserved</summary>

![Cancelled transcription with earlier history preserved](14-after-cancelled.png)

[Open original](14-after-cancelled.png)

</details>

<details>
<summary>Transcript survives switching Generate and Transcribe</summary>

![Transcript survives switching Generate and Transcribe](15-after-mode-return.png)

[Open original](15-after-mode-return.png)

</details>

<details>
<summary>Save failure keeps text and manual download available</summary>

![Save failure keeps text and manual download available](16-after-save-failure.png)

[Open original](16-after-save-failure.png)

</details>

<details>
<summary>Dark mode: transcript and history</summary>

![Dark mode: transcript and history](17-after-dark-history.png)

[Open original](17-after-dark-history.png)

</details>

<details>
<summary>Dark mode: minimal progress and timer</summary>

![Dark mode: minimal progress and timer](18-after-dark-progress.png)

[Open original](18-after-dark-progress.png)

</details>

<details>
<summary>Mobile: dark transcript and history</summary>

![Mobile: dark transcript and history](19-mobile-dark.png)

[Open original](19-mobile-dark.png)

</details>

<details>
<summary>Mobile: light transcript and history</summary>

![Mobile: light transcript and history](19-mobile-light.png)

[Open original](19-mobile-light.png)

</details>

<details>
<summary>Images: unloaded model with saved generation settings</summary>

![Images: unloaded model with saved generation settings](20-images-remembered.png)

[Open original](20-images-remembered.png)

</details>

<details>
<summary>Images: exact saved GGUF model recalled by Generate</summary>

![Images: exact saved GGUF model recalled by Generate](21-images-recalled.png)

[Open original](21-images-recalled.png)

</details>

<details>
<summary>Reduced motion: fixed bars, timer and Cancel</summary>

![Reduced motion: fixed bars, timer and Cancel](22-reduced-motion.png)

[Open original](22-reduced-motion.png)

</details>

<details>
<summary>Transcription completed while visiting Images</summary>

![Transcription completed while visiting Images](23-background-return.png)

[Open original](23-background-return.png)

</details>

<details>
<summary>Final-text-only model: waveform and timer, no partial text</summary>

![Final-text-only model: waveform and timer, no partial text](24-final-only-progress.png)

[Open original](24-final-only-progress.png)

</details>

<details>
<summary>Transcription failure preserves earlier history</summary>

![Transcription failure preserves earlier history](25-transcription-error.png)

[Open original](25-transcription-error.png)

</details>

<details>
<summary>Mobile: history after scrolling the page</summary>

![Mobile: history after scrolling the page](26-mobile-history-scrolled.png)

[Open original](26-mobile-history-scrolled.png)

</details>

<details>
<summary>Mobile: transcript actions menu</summary>

![Mobile: transcript actions menu](27-mobile-history-actions.png)

[Open original](27-mobile-history-actions.png)

</details>

<details>
<summary>Native browser confirmation before discarding an unsaved transcript</summary>

![Native browser confirmation before discarding an unsaved transcript](28-unsaved-warning.png)

[Open original](28-unsaved-warning.png)

</details>

<details>
<summary>Clear history confirmation explains that archived transcripts are kept</summary>

![Clear history confirmation explains that archived transcripts are kept](29-clear-history-warning.png)

[Open original](29-clear-history-warning.png)

</details>

<details>
<summary>History is empty after Clear all</summary>

![History is empty after Clear all](30-cleared-history.png)

[Open original](30-cleared-history.png)

</details>

<details>
<summary>Transcript history with multiple saved sessions</summary>

![Transcript history with multiple saved sessions](31-history-many.png)

[Open original](31-history-many.png)

</details>

<details>
<summary>Older transcripts remain reachable by scrolling</summary>

![Older transcripts remain reachable by scrolling](32-history-scroll.png)

[Open original](32-history-scroll.png)

</details>

<details>
<summary>REAL Qwen3-ASR 0.6B: partial transcript during decoding</summary>

![REAL Qwen3-ASR 0.6B: partial transcript during decoding](33-real-qwen-streaming.png)

[Open original](33-real-qwen-streaming.png)

</details>

<details>
<summary>REAL Qwen3-ASR 0.6B: complete transcript saved to history</summary>

![REAL Qwen3-ASR 0.6B: complete transcript saved to history](34-real-qwen-complete.png)

[Open original](34-real-qwen-complete.png)

</details>

<details>
<summary>REAL whisper.cpp Tiny: timer and Cancel during final-only decoding</summary>

![REAL whisper.cpp Tiny: timer and Cancel during final-only decoding](35-real-whisper-cpp-progress.png)

[Open original](35-real-whisper-cpp-progress.png)

</details>

<details>
<summary>REAL whisper.cpp Tiny: completed transcript and history</summary>

![REAL whisper.cpp Tiny: completed transcript and history](36-real-whisper-cpp-complete.png)

[Open original](36-real-whisper-cpp-complete.png)

</details>

<details>
<summary>REAL Transformers Whisper Tiny: partial text after audio chunks</summary>

![REAL Transformers Whisper Tiny: partial text after audio chunks](37-real-whisper-progress.png)

[Open original](37-real-whisper-progress.png)

</details>

<details>
<summary>REAL Transformers Whisper Tiny: completed transcript and history</summary>

![REAL Transformers Whisper Tiny: completed transcript and history](38-real-whisper-complete.png)

[Open original](38-real-whisper-complete.png)

</details>

<details>
<summary>Browser microphone capture of a speech fixture before real Whisper decoding</summary>

![Browser microphone capture of a speech fixture before real Whisper decoding](39-real-microphone.png)

[Open original](39-real-microphone.png)

</details>

<details>
<summary>Recorded browser audio decoded by real Whisper and saved in history</summary>

![Recorded browser audio decoded by real Whisper and saved in history](40-real-recording-transcript.png)

[Open original](40-real-recording-transcript.png)

</details>

<details>
<summary>REAL image generation: unloaded model and saved recipe</summary>

![REAL image generation: unloaded model and saved recipe](41-real-image-remembered.png)

[Open original](41-real-image-remembered.png)

</details>

<details>
<summary>REAL image generation: recalled model is generating with the saved recipe</summary>

![REAL image generation: recalled model is generating with the saved recipe](42-real-image-loading.png)

[Open original](42-real-image-loading.png)

</details>

<details>
<summary>REAL Segmind Vega: generated image in Studio history</summary>

![REAL Segmind Vega: generated image in Studio history](44-real-image-complete.png)

[Open original](44-real-image-complete.png)

</details>

## Reports, logs and generated files

- [logs/backend-tests.log](logs/backend-tests.log)
- [logs/frontend-tests.log](logs/frontend-tests.log)
- [logs/ruff.log](logs/ruff.log)
- [logs/typecheck-build.log](logs/typecheck-build.log)
- [mutation-checks.json](mutation-checks.json)
- [real-image/direct-api-response.json](real-image/direct-api-response.json)
- [real-image/pixel-integrity.json](real-image/pixel-integrity.json)
- [real-image/report.md](real-image/report.md)
- [real-image/server.log](real-image/server.log)
- [real-image/ui-checks.json](real-image/ui-checks.json)
- [real-native/checks.json](real-native/checks.json)
- [real-native/gpu-evidence.json](real-native/gpu-evidence.json)
- [real-native/qwen-after-cancel.json](real-native/qwen-after-cancel.json)
- [real-native/qwen-cancelled.json](real-native/qwen-cancelled.json)
- [real-native/qwen-events.json](real-native/qwen-events.json)
- [real-native/runtime.json](real-native/runtime.json)
- [real-native/whisper-cpp-after-cancel.json](real-native/whisper-cpp-after-cancel.json)
- [real-native/whisper-cpp-cancelled.json](real-native/whisper-cpp-cancelled.json)
- [real-native/whisper-cpp-final.json](real-native/whisper-cpp-final.json)
- [real-recording.txt](real-recording.txt)
- [real-whisper/cancel-events.ndjson](real-whisper/cancel-events.ndjson)
- [real-whisper/cancel-worker-cpu-after.txt](real-whisper/cancel-worker-cpu-after.txt)
- [real-whisper/cancel-worker-cpu-before.txt](real-whisper/cancel-worker-cpu-before.txt)
- [real-whisper/complete-events.ndjson](real-whisper/complete-events.ndjson)
- [real-whisper/download.log](real-whisper/download.log)
- [real-whisper/gpu-events.ndjson](real-whisper/gpu-events.ndjson)
- [real-whisper/gpu-process-samples.txt](real-whisper/gpu-process-samples.txt)
- [real-whisper/report.md](real-whisper/report.md)
- [real-whisper/torch-gated-test.log](real-whisper/torch-gated-test.log)
- [retention-before-after.json](retention-before-after.json)
- [ui-checks.json](ui-checks.json)
- [verification.md](verification.md)
- [video-playback.json](video-playback.json)
- [real-image/direct-api-teapot.png](real-image/direct-api-teapot.png)
- [real-image/ui-recall-teapot-first.png](real-image/ui-recall-teapot-first.png)
- [real-image/ui-recall-teapot-via-route.png](real-image/ui-recall-teapot-via-route.png)

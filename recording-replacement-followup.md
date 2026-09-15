# Recording replacement follow-up

Commit: `b30076752`.

When history persistence failed, the original Record flow asked whether to discard the old transcript only after microphone capture had finished. Declining then dropped the new recording. The fix asks before model preparation or capture and carries the accepted transcript version into the stop callback. A different transcript still requires its own confirmation.

Two executable callback regression tests failed on the original code and passed after the fix:

- Declining replacement prevents recording setup. Before: model preparation ran without confirmation. After: confirmation runs first and declining returns immediately.
- Recording approval applies once and only to the transcript it covered. Approval for the same version avoids a second prompt. An older version or no approval still prompts.

Executed from the repository root:

```sh
node --experimental-strip-types --test studio/frontend/tests/audio-transcript-lifecycle.test.ts studio/frontend/tests/audio-page-policy.test.ts studio/frontend/tests/audio-model-eject.test.ts
```

Result: 73 passed, zero failed.

Executed from `studio/frontend`:

```sh
node node_modules/typescript/bin/tsc -b --pretty false
node node_modules/typescript/bin/tsc -p tsconfig.test.json --pretty false
```

Both passed. No model download or repeated inference was needed for this control-flow correction. Existing screenshots and recordings document the feature at `4f8cfdf58`; this report documents the subsequent recording guard fix.

The formatting commit `588130be9` changed seven Python files; all seven had identical parsed syntax trees before and after.

## macOS termination and archive-flag recovery

Commit: `6641484f6`.

The AppKit termination predicate now includes the unsaved-transcript flag, so an unsaved transcript alone enters the shared confirmation sequence. A source-wiring regression failed on the missing flag and passed after adding it. This checks the connection between the predicate and confirmation path; it does not execute a native macOS dialog.

Transcript listing now uses the existing display-only archive-flag reader. Malformed flags and valid recovery-tainted flags both previously caused listing to fail while intact transcript records remained on disk. Both regression cases now pass, and Clear all still refuses to delete when the flags cannot be trusted.

```sh
python -m pytest studio/backend/tests/test_transcript_gallery.py studio/backend/tests/test_gallery_flags.py -q
node --experimental-strip-types --test studio/frontend/tests/audio-transcript-lifecycle.test.ts
```

Results: 53 backend tests passed; six transcript lifecycle tests passed. The frontend test TypeScript check and repository formatter/checker with Ruff 0.6.9 also passed.

[Apple's termination delegate documentation](https://developer.apple.com/documentation/appkit/nsapplicationdelegate/applicationshouldterminate%28_%3A%29) describes the immediate, deferred, and cancelled termination replies used by the native path.

## Quantized image recall with selected adapters

Commit: `26296a370`.

Ejecting a quantized image model clears its resident identity but retains the LoRA selection. Recall previously derived advanced load parameters as if this were a different model, dropping those adapters from the build. Recall now explicitly preserves the selection while pinning the advanced load parameters. Regular model picks retain their same-target filtering.

The regression executes the actual recall and advanced-parameter callbacks from `images-page.tsx`. It failed before the fix because the load did not carry the selected adapter. It passes for int8 and fp8 settings after the fix, including adapter ID normalization, disabled-adapter filtering, exact GGUF filename retention, and isolation from an unrelated model pick.

```sh
node --experimental-strip-types --test studio/frontend/tests/image-model-recall.test.ts
```

All three image recall tests passed. Application and test TypeScript checks also passed. This verifies load parameters at the callback boundary; a new GPU generation run with a quantized model and LoRA was not performed.

## Streaming cancellation refutation

Checked at `26296a370`; no source change was needed.

The streaming call passes `request=None` but supplies `on_progress`, so `_transcribe_audio_result` creates a real cancellation event. Closing `stream_transcript` cancels its producer task. The route catches `asyncio.CancelledError` and calls `sidecar.cancel_transcription(cancel_event)` on a short-lived thread. Every supported sidecar sets that event before checking its owned load.

A direct reproduction ran the actual stream generator and route coroutine, with real cancellation methods from WhisperSttSidecar, MtmdSttSidecar, and GgmlSttSidecar. Only model loading and transcription work were replaced by a bounded blocking worker. Each worker received its cancellation event, exited, and produced no saved transcript. Result: three tests passed in 0.85 seconds. [Executable probe](test_stream_cancel_refutation.py).

This agrees with the previously published [real Whisper cancellation and recovery](real-whisper/report.md) and [real Qwen/whisper.cpp results](real-native/checks.json). The existing implementation already handles the reported case.

[Python's task cancellation documentation](https://docs.python.org/3/library/asyncio-task.html#task-cancellation) specifies that cancellation raises CancelledError inside the task, allowing this explicit cleanup path to run. The code does not rely on cancelling an asyncio task to stop a thread by itself.

## Clear-all error handling

Checked at `26296a370`; no source change was needed. The proposed 500-to-503 mapping would improve the message for unavailable archive metadata. Destructive clearing already stops before deleting records, and the UI already catches the failed request.

[Executed callback probe](check-clear-error.mjs) extracted the actual API wrapper, shared error parser, and gallery mutation callback. Both 500 and 503 responses displayed an error without calling the deletion callback or refreshing away the current history. Two scenarios passed. Existing backend regression checks also establish that corrupt or recovery-tainted archive flags preserve transcript records.

This suggestion was declined as error-message polish, rather than a demonstrated data-loss or UI-state defect.

## Archive-view mutation race

Commit: `1dec588b0`.

An Archive/Delete request that finished after switching History/Archived previously called the old render's refresh function. The completed request could replace Archived rows with History rows, or vice versa. Mutation completion now calls the latest committed refresh callback.

The regression executes the component's actual hook statements with deferred mutation completion. It failed before the fix with fetches `[true, false]` after switching to Archived, and passes after the fix. It covers both switching directions and remaining in the same view.

```sh
node --experimental-strip-types --test studio/frontend/tests/transcript-gallery-mutation.test.ts studio/frontend/tests/audio-transcript-lifecycle.test.ts studio/frontend/tests/transcript-stream.test.ts
```

Result: 11 focused tests passed. Application and test TypeScript checks passed. The changed gallery component passed ESLint. This was a callback-order regression check; a new browser recording was not captured for the race fix.

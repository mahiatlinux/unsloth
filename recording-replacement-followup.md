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

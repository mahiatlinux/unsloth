# PR 8759 evidence (disposable)

Staging branch for UI evidence on upstream [unslothai/unsloth#8759](https://github.com/unslothai/unsloth/pull/8759),
"studio: newline-terminate exported jsonl records". Not code, not for merge.

Shot from two isolated Studio installs, merge base `32c2627ae` vs head `3c5d95776`, driven
through the same scene: chat -> + -> Saved prompts -> All saved prompts -> Export ->
All Prompts / JSONL -> Download, with the same three prompts seeded in both homes.

`.github/workflows/pr8759-evidence.yml` re-checks every number quoted on the PR against
the files in `evidence/` and uploads them as the `pr8759-evidence` artifact.

| File | What it is |
|---|---|
| `evidence/before_prompts.jsonl` | the export from the merge-base build, 251 bytes, ends `..."}` |
| `evidence/after_prompts.jsonl` | the export from the PR head build, 252 bytes, ends `..."}\n` |
| `evidence/pr8759_before_after.png` | labelled BEFORE\|AFTER composite: the Export dialog above the bytes it produced |
| `evidence/before_export_dialog.png` | the Export dialog on the merge-base build |
| `evidence/after_export_dialog.png` | the same dialog on the head build, byte-identical to the one above |

The dialog screenshots are identical on purpose: the PR edits no markup, so the change
exists only in the downloaded file.

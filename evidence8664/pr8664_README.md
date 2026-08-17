# PR 8664 UI evidence

Before/after evidence for `unslothai/unsloth#8664`, "retire the audio page load spinner
on every exit path". Disposable branch; nothing here is meant to be merged.

- BEFORE: `b3376300e5a5470b658ea918c854f244152a7804`, the PR's merge base
- AFTER: `df4140a8ff50eb3bf04af4e600fc2342dacdbec6`, the PR head
- Two separate Studio installs, one per commit, each with its own `UNSLOTH_STUDIO_HOME`,
  each on its own port, each verified by logging in with that home's own credential.

## What the scene does

`ensureSttLoaded` raises `toast.loading("Preparing <key>…")` and only shows a terminal
toast while `isCurrent()` holds. The old `finally` dismissed the spinner in one case
only, when the generation had already moved on. The hole is the opposite ordering: the
attempt is still the current generation while it stops being current for another reason.

`isCurrent()` also compares `selectedSttRepoRef` against the repo being loaded, and
`refreshSttStatus` moves that ref onto whatever the sidecar reports resident
(`reconcileSttSelection`). So, on the Audio page in Transcribe mode:

1. Pick `unsloth/whisper-tiny`. `POST /api/inference/audio/stt/load` is held open by the
   browser context's router, so the attempt stays in flight and the spinner stays up. No
   weights are read and no GPU is used.
2. `GET /api/inference/audio/stt/status` is proxied to the real Studio with one field
   rewritten, `transformers.loaded_model` -> `small`. This box has no dictation model
   resident and no second sidecar to load one, so another surface's outcome is supplied
   rather than performed.
3. The page is given the announcement it would hear from that surface, its own
   `unsloth:model-lifecycle` stt event. It re-reads the status, reconciles, and the
   picker moves to Whisper Small. The in-flight attempt now belongs to nobody, with its
   generation still current and its spinner still up.
4. The held load is released `200`.

Both installs get identical routed responses and the same event. What differs is only
what each build does with an attempt it no longer owns.

## Result

| | BEFORE | AFTER |
|---|---|---|
| `stuck_toast_present` | true | false |
| `toast_count` | 1 | 0 |
| `toast_texts` | `["Preparing tiny…"]` | `[]` |
| `stuck_toast_after_20s` | true | false |

Controls that matched on both sides: `stt_resident_at_start` null, `load_requests` 1,
`picker_rows_matched` 1, `status_reads` 2, `selection_after_pick` "Whisper Tiny",
`selection_after_reconcile` "Whisper Small", and `toasts_before_release`
`["Preparing tiny…"]` on both, so the leak is in the settle and not in the raise.

A sonner `loading` toast is never given a timer, so on BEFORE the spinner stays for the
life of the tab.

## Files

- `pr8664_toast_corner_before_after.png` - the toast corner, 1:1
- `pr8664_audio_page_before_after.png` - the whole page, both halves
- `pr8664_before.webm`, `pr8664_after.webm` - the Playwright recordings the GIFs come from
- `pr8664_before.gif`, `pr8664_after.gif` - built in CI, since the recording box has no
  system ffmpeg (Chromium records the webms with the one Playwright ships). Whole
  recordings, one GIF per side, not stacked into a single loop: the two runs are
  separate sessions and a shared frame would imply a synchronisation nothing here
  establishes.
- `pr8664_before_timeline.json`, `pr8664_after_timeline.json` - elapsed seconds for each
  step of each run, from the recording's own clock
- `pr8664_meta.json` - commits, scene, and the full fact sets

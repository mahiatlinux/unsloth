# PR 8514 geometry, before/after

Base `34a119764` (the PR's merge base) against head `aa40cace3`,
two isolated Studio installs, one scene, a seeded 60-chat history at 1280x900.
Posted inline at https://github.com/unslothai/unsloth/pull/8514#issuecomment-5315401516

## Published summary

Straight from `meta.json` of the run whose composites are in this artifact.

| | before | after |
| --- | --- | --- |
| list height at open, still loading | 71 px | 420 px |
| list height once 60 rows land | 420 px | 420 px |
| list resizes during the open | 1 | 0 |
| size of that resize | 349 px | 0 px |
| last resize, after open | 1135 ms | 0 ms |
| centred surface travel | 177 px | 11 px |
| list height with 2 of 60 matching | 83 px | 420 px |
| reopen: rows painted at 320 ms | 0 | 60 |

## Per-frame series

A `requestAnimationFrame` sampler read the list's `offsetHeight` and the surface's
`getBoundingClientRect()` once per frame from the keypress until the rows settled.
Raw series: `before_open_frames.json`, `after_open_frames.json`, and the same two for
the reopen. Each entry is `{t (ms from sampler start), lh (list offsetHeight), st
(surface top), sh (surface height), rows, opts, loading}`.

These series come from a RE-CAPTURE against the same two installs, because the first
run reduced its samples in memory and kept only the summary above. The geometry
reproduces exactly; the frame COUNT does not, and cannot, since it depends on how
loaded the box was. That is also why no frame-rate claim is made anywhere here.

| side | phase | frames | runs of equal list height (height x frames, t range) |
| --- | --- | --- | --- |
| before | open | 112 | 71 px x 61 (80-1123 ms); 420 px x 51 (1152-1973 ms) |
| before | reopen | 23 | 71 px x 23 (63-450 ms) |
| after | open | 111 | 420 px x 111 (54-1955 ms) |
| after | reopen | 24 | 420 px x 24 (72-475 ms) |

## Surface geometry at the sampled edges

| side | phase | first (top, height) | last (top, height) |
| --- | --- | --- | --- |
| before | open | 393 px, 114 px | 216 px, 469 px |
| before | reopen | 393 px, 114 px | 390 px, 120 px |
| after | open | 227 px, 446 px | 216 px, 469 px |
| after | reopen | 227 px, 446 px | 216 px, 469 px |

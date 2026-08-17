# PR 8514 evidence, method and limits

Inline version of this evidence: https://github.com/unslothai/unsloth/pull/8514#issuecomment-5315401516

## What is in here

| file | what it is |
| --- | --- |
| `pr8514_pair_00.png` | first open, index still resolving. Base collapses to 120 px, head is already 469 px. |
| `pr8514_pair_01.png` | query `quantile calibration`, 2 of 60 chats matching. Base shrinks to 132 px, head holds 469 px. |
| `pr8514_pair_02.png` | closed and reopened. Base is back to "Loading...", head paints 60 cached rows. |
| `geometry_table.md` | the published summary table plus the per-frame series collapsed into runs. |
| `geometry_summary.json` | the exact `facts` block from the published run's `meta.json`. |
| `before_open_frames.json`, `after_open_frames.json` | the raw per-frame rAF series across the first open. |
| `before_reopen_frames.json`, `after_reopen_frames.json` | the same across the reopen. |
| `before_session.webm`, `after_session.webm` | the browser's own recording of each side's session. |
| `before_open.gif`, `after_open.gif` | those recordings converted to gif in CI. |
| `chat_search_open_stability.py` | the scene, so all of the above is reproducible. |

## How the frames were made

Chromium recorded the webms itself, through Playwright, at whatever cadence it actually
drew. The box that ran the browser has no system ffmpeg, so the gif conversion is the one
step done on the runner: two-pass palette, `fps=10`, 720 px wide. That resampling is for
file size. It is not a frame-rate measurement and must not be read as one.

The recordings cover a whole scene run: page load, the seeded history arriving, the first
open, the filter, the close and the reopen. They are not trimmed to the animation, because
trimming to a fixed offset would have implied an alignment between the two sides that
nothing here establishes. For the same reason the two gifs are separate rather than stacked
into one before/after clip.

## What is deliberately not claimed

No wall-clock or frame-rate figure. This box ran the two published sides at load average
15.9 and 6.8 on 16 cores with seven other agents installing, and the runner's load is no
better controlled, so any such number would be noise. Every figure in
`geometry_table.md` is layout geometry, which host load does not move.

Load averages recorded at capture time:

```json
{
  "published_before": {
    "loadavg_1m_5m_15m": [
      15.8974609375,
      10.13916015625,
      4.9482421875
    ],
    "cpu_count": 16
  },
  "published_after": {
    "loadavg_1m_5m_15m": [
      6.78271484375,
      8.65869140625,
      5.04443359375
    ],
    "cpu_count": 16
  },
  "recapture_before": {
    "loadavg_1m_5m_15m": [
      1.61572265625,
      2.2939453125,
      3.37109375
    ],
    "cpu_count": 16
  },
  "recapture_after": {
    "loadavg_1m_5m_15m": [
      2.5185546875,
      2.42724609375,
      3.36474609375
    ],
    "cpu_count": 16
  }
}
```

The loading window in pair 00 is held open by a fixed 500 ms Playwright route delay on
`/api/chat/threads` and `/api/chat/messages:batch`, applied identically to both sides.
Unheld it is a few tens of milliseconds here and that shot is a coin toss. The delay holds
the moment still; it does not produce the difference, since the head decides its height in
the opening render from `chatSearchIndexHasRows()` before either request returns, and pairs
01 and 02 use no delay at all.

The WebKit compositing argument in the PR description cannot be checked here. This is
Chromium on Linux.

## Side identity

Checked per side rather than assumed, because the port range is shared with other agents:
`ss` mapped each port to the pid whose `UNSLOTH_STUDIO_HOME` is that side's home; each
home's own `studio.db` held the 60 rows the scene seeded through that port; and the bundle
served on the head port carried `unsloth_chat_search_has_rows` and the
`h-[420px] max-h-[60dvh]` pair while the base port carried neither, only `max-h-[420px]`.
Main bundle hashes differed too (`index-Du5KHhFa` vs `index-cJEdkY7Y`).

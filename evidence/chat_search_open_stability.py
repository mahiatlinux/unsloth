"""Scene: the chat search dialog (Ctrl+K) at open, while filtering, and on reopen.

Serves PR 8514, which is a TIMING fix -- so a naive still pair proves nothing. The
thing the PR actually changes is a layout decision, and that IS photographable:

  BEFORE  `CommandList` is `max-h-[420px]`, so the list is only as tall as whatever
          it currently holds. On open the index has not been built, the list holds
          one "Loading..." row, and the surface is ~100 px tall. When the rows land
          it snaps to 420 px, and because the dialog is centred with
          `top-1/2 -translate-y-1/2` that also moves both edges at once.
  AFTER   `h-[420px] max-h-[60dvh]` whenever the history is not known-empty, decided
          in the opening render from `chatSearchIndexHasRows()`. One height for the
          whole open: loading, rows arriving, and filtering all leave it alone.

Three moments are shot because each isolates one claim, and none of them is the
same picture on both sides:

  01_open_loading   the first open, index still resolving
  02_filtered       a query matching 2 of the seeded chats (BEFORE shrinks to the
                    result count, AFTER holds 420 px)
  03_reopen         closed and reopened (BEFORE flashes "Loading..." again, AFTER
                    paints the module-level `cachedIndex` at once)

The numbers come from a requestAnimationFrame sampler reading the list's
`offsetHeight` and the surface's `getBoundingClientRect()` per frame across the
open. Those are LAYOUT readings, not wall clock, so a loaded host changes how many
frames are sampled but not the heights or the size of the jump -- which is the
claim. Nothing here loads a model or touches the GPU.

History is seeded through the REST API of the very Studio being photographed, with
fixed ids, titles and timestamps, so both sides index byte-identical input. The
timestamps are deliberately over 30 days old: `formatRelative` would otherwise
print "Today" on one side and something else on the other if a run straddled
midnight.

Both chat routes the index reads are delayed by a fixed amount via a Playwright
route handler, installed AFTER page load and identically on both sides. Without it
the loading window on this box is a few tens of milliseconds and the first shot is
a coin toss. The delay does not create the effect; it holds the moment still.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

WORKSPACE = Path(os.environ.get("UNSLOTH_WORKSPACE", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from pr_ui_scenes._common import Session, api_get  # noqa: E402
from studio_test_kit.auth import seed_init_script  # noqa: E402
from studio_test_kit.ui import open_chat  # noqa: E402

# 2025-01-15T00:00:00Z. Fixed, and far enough back that every row reads "Older" on
# both sides no matter when the run happens.
SEED_EPOCH_MS = 1_736_899_200_000

# The list element. `data-slot` is set by components/ui/command.tsx and is stable on
# both sides; cmdk's own `cmdk-list` attribute is read as a fallback only.
LIST_SEL = '[data-slot="command-list"]'
SURFACE_SEL = ".chat-search-surface"

# Both tokens together appear in exactly two seeded titles, so filtering leaves a
# result count far below the full history and the BEFORE list has to shrink to it.
# "quantile" alone would hit four rows, since the topic list repeats at 60 threads.
FILTER_QUERY = "quantile calibration"

# The newest seeded chat, so a row can be waited on by its text rather than by a
# cmdk attribute. A selector that matches nothing would otherwise photograph an
# empty dialog on both sides, which reads as "the PR changed nothing".
NEWEST_ROW_TITLE = "lora rank sweep 000"

TOPICS = [
    "lora rank sweep", "tokenizer padding side", "gguf export failed",
    "grad checkpointing oom", "rope scaling long context", "bnb 4bit vs 8bit",
    "eos token duplicated", "dataset shuffle seed", "flash attention build",
    "vram fragmentation", "chat template jinja", "resume from checkpoint",
    "learning rate warmup", "packing short samples", "eval loss plateau",
    "merge adapter weights", "quantile calibration sweep", "triton kernel autotune",
    "multi gpu sharding", "sft to dpo handoff", "tool call schema",
    "streaming stop tokens", "prompt cache reuse", "sequence length clamp",
    "quantile loss debugging", "logit soft capping", "vocab resize mismatch",
    "safetensors shard order", "cuda graph capture", "attention mask leak",
]


def _req(session: Session, method: str, path: str, payload: dict | None = None,
         timeout: int = 120) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{session.base_url}{path}", data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {session.access_token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def seed_history(session: Session, count: int) -> list[str]:
    """Create `count` chats with one user and one assistant message each.

    Every thread needs at least one message: `buildIndex` drops an empty thread, so
    seeding threads alone yields a dialog that says "No chats yet." on both sides.

    Ids and timestamps are fixed, and POST /api/chat/threads upserts, so re-running
    against a reused home re-seeds the same rows rather than accumulating.
    """
    titles: list[str] = []
    for i in range(count):
        topic = TOPICS[i % len(TOPICS)]
        tid = f"uidiff8514-t{i:03d}"
        title = f"{topic} {i:03d}"
        titles.append(title)
        # Descending createdAt, one minute apart, so the row order is decided by the
        # seed rather than by which write the server happened to finish first.
        created = SEED_EPOCH_MS - i * 60_000
        _req(session, "POST", "/api/chat/threads", {
            "id": tid, "title": title, "modelType": "base", "modelId": "",
            "createdAt": created, "updatedAt": created, "archived": False,
        })
        _req(session, "PUT", f"/api/chat/threads/{tid}/messages", {
            "messages": [
                {"id": f"{tid}-m0", "threadId": tid, "role": "user",
                 "content": [{"type": "text", "text": f"How do I fix {topic}?"}],
                 "createdAt": created},
                {"id": f"{tid}-m1", "threadId": tid, "role": "assistant",
                 "content": [{"type": "text",
                              "text": f"Start by checking the {topic} configuration."}],
                 "createdAt": created + 1_000},
            ],
            "pruneMissing": True,
        })
    return titles


# Samples the list's layout height and the surface's on-screen box once per frame.
# offsetHeight is the LAYOUT height, unaffected by the zoom transform; the surface
# rect is what re-centring moves, and is read from the same frame so the two agree.
_SAMPLER_JS = """
(sel) => {
  const [listSel, surfaceSel] = sel;
  const probe = { samples: [], stop: false, t0: performance.now() };
  window.__uidiffProbe = probe;
  const tick = () => {
    const list = document.querySelector(listSel) ||
                 document.querySelector('[cmdk-list]');
    const surface = document.querySelector(surfaceSel);
    if (list) {
      const sr = surface ? surface.getBoundingClientRect() : null;
      const text = list.innerText || "";
      probe.samples.push({
        t: Math.round(performance.now() - probe.t0),
        lh: list.offsetHeight,
        st: sr ? Math.round(sr.top) : null,
        sh: sr ? Math.round(sr.height) : null,
        rows: list.querySelectorAll('[cmdk-item]').length,
        opts: list.querySelectorAll('[role="option"]').length,
        loading: text.includes('Loading'),
      });
    }
    if (!probe.stop) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""

_READ_STATE_JS = """
(sel) => {
  const [listSel, surfaceSel] = sel;
  const list = document.querySelector(listSel) || document.querySelector('[cmdk-list]');
  const surface = document.querySelector(surfaceSel);
  if (!list) return null;
  const sr = surface ? surface.getBoundingClientRect() : null;
  const text = list.innerText || "";
  return {
    lh: list.offsetHeight,
    sh: sr ? Math.round(sr.height) : null,
    st: sr ? Math.round(sr.top) : null,
    rows: list.querySelectorAll('[cmdk-item]').length,
    opts: list.querySelectorAll('[role="option"]').length,
    loading: text.includes('Loading'),
    empty_msg: text.includes('No chats'),
  };
}
"""


def _dump_frames(samples: list[dict], out_dir: Path, label: str, prefix: str) -> Path:
    """Persist the raw per-frame series next to the summary.

    Added after the first published run, which reduced the samples in memory and threw
    the series away: `facts` then carried the claim with no way to expand it. Writing
    the frames changes no measurement, and a reviewer asking "how many frames held 71
    px?" has nowhere else to look.
    """
    path = out_dir / f"{label.lower()}_{prefix}_frames.json"
    path.write_text(json.dumps(samples, indent=1))
    return path


def _summarise(samples: list[dict], prefix: str) -> dict:
    """Reduce a frame series to the claims: first height, settled height, the jump."""
    if not samples:
        return {f"{prefix}_frames": 0}
    heights = [s["lh"] for s in samples]
    tops = [s["st"] for s in samples if s["st"] is not None]
    changes = sum(1 for a, b in zip(heights, heights[1:]) if a != b)
    settled_at = 0
    for i in range(1, len(heights)):
        if heights[i] != heights[i - 1]:
            settled_at = samples[i]["t"]
    out = {
        f"{prefix}_frames": len(samples),
        f"{prefix}_list_h_first_px": heights[0],
        f"{prefix}_list_h_last_px": heights[-1],
        f"{prefix}_list_h_jump_px": heights[-1] - heights[0],
        f"{prefix}_list_h_distinct": len(sorted(set(heights))),
        f"{prefix}_list_h_changes": changes,
        f"{prefix}_list_h_series": sorted(set(heights)),
        f"{prefix}_last_resize_at_ms": settled_at,
    }
    if tops:
        out[f"{prefix}_surface_top_first_px"] = tops[0]
        out[f"{prefix}_surface_top_last_px"] = tops[-1]
        out[f"{prefix}_surface_top_travel_px"] = max(tops) - min(tops)
    return out


async def _open_dialog(page) -> None:
    """Press Ctrl+K with the keyboard, and prove the dialog actually opened.

    The handler in chat-search-dialog.tsx ignores the shortcut while an INPUT or
    TEXTAREA has focus, and /chat autofocuses the composer, so a bare key press is
    swallowed and the "before" shot ends up being of the chat page. Blur first, then
    assert on the dialog's own placeholder -- not on a heading: the surface has no
    visible heading at all (the DialogTitle is sr-only), so `assert_showing` would
    pass against the sr-only node while the dialog stayed shut.
    """
    await page.evaluate(
        "() => { const el = document.activeElement;"
        " if (el && el instanceof HTMLElement) el.blur(); }"
    )
    await page.keyboard.press("Control+k")
    await page.get_by_placeholder("Search chats...").wait_for(state="visible", timeout=15_000)


async def drive(session: Session, out_dir: Path, label: str,
                threads: int = 60, api_delay_ms: int = 500,
                clip: dict | None = None, video: bool = False,
                **_: object) -> tuple[list[Path], dict]:
    """Shoot the three moments and return the per-frame geometry beside them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    facts: dict = {}

    seed_history(session, threads)
    # The numeric control: both sides must index the SAME history, so a pair whose
    # heights differ because one side has fewer chats is caught here rather than
    # being read as the fix.
    facts["seeded_thread_count"] = api_get(session, "/api/chat/count").get("count")

    # Host load beside the geometry, deliberately NOT in `facts`: seven agents share
    # this box, so load moves between the two sides and would satisfy the driver's
    # "some fact differed" guard on its own.
    (out_dir / "host_load.json").write_text(json.dumps({
        "loadavg_1m_5m_15m": os.getloadavg(), "cpu_count": os.cpu_count(),
    }))

    shots: list[Path] = []
    init = seed_init_script(
        type("A", (), {"access_token": session.access_token,
                       "refresh_token": session.refresh_token})(), []
    )
    # A FIXED clip, identical on both sides, centred on where the dialog sits. An
    # element screenshot would crop to the surface, and the surface SIZE is the whole
    # claim: hstack_images equalises heights by scaling, so a tight crop of a 100 px
    # dialog would be blown up to match a 480 px one and the pair would prove the
    # opposite of what it shows.
    shot_clip = clip or {"x": 280, "y": 120, "width": 720, "height": 660}
    # Chromium writes the webm itself through Playwright's own bundled ffmpeg, so a box
    # with no system ffmpeg still records REAL frames at the cadence the browser drew
    # them. Converting to a gif needs a system ffmpeg and is left to whoever has one.
    video_dir = (out_dir / "video") if video else None
    async with open_chat(session.base_url, init_scripts=[init],
                         video_dir=video_dir, video_name=f"{label.lower()}_session",
                         viewport=(1280, 900), headless=True) as sp:
        page = sp.page
        await page.locator("form:has(textarea) textarea").first.wait_for(
            state="visible", timeout=60_000
        )
        # Let the sidebar's own history load settle BEFORE the routes are slowed, so
        # the delay applies to the dialog's index build and nothing else.
        await page.wait_for_timeout(4_000)

        async def _slow(route):
            await asyncio.sleep(api_delay_ms / 1000)
            await route.continue_()

        # The two reads buildIndex makes. `threads*` cannot match
        # /threads/<id>/messages: a glob `*` does not cross a path separator.
        await page.route("**/api/chat/threads*", _slow)
        await page.route("**/api/chat/messages:batch", _slow)

        # ── 1. first open, index still resolving ────────────────────────────────
        await page.evaluate(_SAMPLER_JS, [LIST_SEL, SURFACE_SEL])
        await _open_dialog(page)
        await page.wait_for_timeout(320)
        state = await page.evaluate(_READ_STATE_JS, [LIST_SEL, SURFACE_SEL])
        if state is None:
            raise RuntimeError(f"[{label}] the command list never mounted: {LIST_SEL} "
                               "matched nothing, so the shot is of the chat page")
        facts["shot1_loading"] = state["loading"]
        facts["shot1_list_h_px"] = state["lh"]
        facts["shot1_surface_h_px"] = state["sh"]
        facts["shot1_rows"] = state["rows"]
        shot = out_dir / f"{label.lower()}_01_open_loading.png"
        await page.screenshot(path=str(shot), clip=shot_clip)
        shots.append(shot)

        # Rows land once the delayed batch answers. Fail loudly rather than shooting
        # an empty dialog twice: a scene that photographs "No chats yet." on both
        # sides is a clean-looking pair that proves nothing.
        try:
            await page.get_by_text(NEWEST_ROW_TITLE, exact=True).first.wait_for(
                state="visible", timeout=60_000
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"[{label}] the row {NEWEST_ROW_TITLE!r} never appeared in the search "
                f"dialog, so the seed did not reach the index "
                f"(server count={facts['seeded_thread_count']})"
            ) from exc
        await page.wait_for_timeout(1_500)
        settled = await page.evaluate(_READ_STATE_JS, [LIST_SEL, SURFACE_SEL])
        facts["settled_list_h_px"] = settled["lh"]
        facts["settled_rows"] = settled["rows"]
        probe = await page.evaluate(
            "() => { const p = window.__uidiffProbe; p.stop = true; return p.samples; }"
        )
        facts.update(_summarise(probe, "open"))
        _dump_frames(probe, out_dir, label, "open")

        # ── 2. filtering, with the index already built ──────────────────────────
        box = page.get_by_placeholder("Search chats...")
        await box.fill(FILTER_QUERY)
        # Past useDeferredValue and past FULL_ROW_REVEAL_MS, so the shot is of the
        # settled filtered state on both sides rather than of one side mid-transition.
        await page.wait_for_timeout(1_500)
        filtered = await page.evaluate(_READ_STATE_JS, [LIST_SEL, SURFACE_SEL])
        facts["shot2_query"] = FILTER_QUERY
        facts["shot2_list_h_px"] = filtered["lh"]
        facts["shot2_surface_h_px"] = filtered["sh"]
        facts["shot2_rows"] = filtered["rows"]
        if filtered["rows"] == 0 and filtered["opts"] == 0:
            raise RuntimeError(
                f"[{label}] the query {FILTER_QUERY!r} matched nothing, so the pair "
                "would show two empty dialogs. Fix the seeded titles."
            )
        shot = out_dir / f"{label.lower()}_02_filtered.png"
        await page.screenshot(path=str(shot), clip=shot_clip)
        shots.append(shot)

        # ── 3. close, reopen ───────────────────────────────────────────────────
        await page.keyboard.press("Escape")
        await page.get_by_placeholder("Search chats...").wait_for(
            state="hidden", timeout=15_000
        )
        # Past the 180 ms exit and the hook's 300 ms ROW_RELEASE_DELAY_MS, so the
        # reopen is a genuine cold open on BEFORE and a genuine cache hit on AFTER.
        await page.wait_for_timeout(1_200)
        await page.evaluate(_SAMPLER_JS, [LIST_SEL, SURFACE_SEL])
        await _open_dialog(page)
        await page.wait_for_timeout(320)
        reopened = await page.evaluate(_READ_STATE_JS, [LIST_SEL, SURFACE_SEL])
        facts["shot3_loading"] = reopened["loading"]
        facts["shot3_list_h_px"] = reopened["lh"]
        facts["shot3_surface_h_px"] = reopened["sh"]
        facts["shot3_rows"] = reopened["rows"]
        shot = out_dir / f"{label.lower()}_03_reopen.png"
        await page.screenshot(path=str(shot), clip=shot_clip)
        shots.append(shot)
        probe = await page.evaluate(
            "() => { const p = window.__uidiffProbe; p.stop = true; return p.samples; }"
        )
        facts.update(_summarise(probe, "reopen"))
        _dump_frames(probe, out_dir, label, "reopen")

    if video and sp.video_webm is not None:
        facts["video_webm"] = sp.video_webm.name
    return shots, facts


if __name__ == "__main__":
    import argparse

    from pr_ui_scenes._common import studio_session

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default="AFTER")
    ap.add_argument("--threads", type=int, default=60)
    ap.add_argument("--video", action="store_true",
                    help="record the session webm as well (real frames, no gif)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    s = studio_session(a.url, a.home, a.password)
    print(json.dumps(asyncio.run(
        drive(s, a.out, a.label, threads=a.threads, video=a.video)
    )[1], indent=2))

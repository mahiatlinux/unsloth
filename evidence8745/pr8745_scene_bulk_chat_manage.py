# SPDX-License-Identifier: AGPL-3.0-only
"""Scene: Settings > Data, and the bulk chat manager PR 8745 adds behind it.

PR 8745 mounts one new `SettingsRow` ("Manage chats") in `data-tab.tsx` between the
"Use chats as training data" row and "Archived chats", and adds a `manage` subpage
rendering `ManageChatsView` with a checkbox table plus a Move/Pin/Archive/Export/Delete
toolbar. Nothing on the merge base can reach that subpage: the row, the subpage branch
and the component all arrive with this PR.

So the honest surface is the Data panel scrolled to the top, with the insertion point in
frame. "Use chats as training data" is the control: this PR does not touch it, so it must
render identically on both halves; if it does not, the panel failed to load and the pair
says nothing about bulk management.

Two shots per side, kept index-comparable:

  0  the Data panel at rest -- "Manage chats" absent vs present, with its Manage button
  1  AFTER: the manage subpage with three chats ticked, so the toolbar is enabled and the
     counter reads "3 chats selected". On BEFORE there is no row to click, so the shot
     repeats shot 0. That asymmetry IS the result; do not branch around it.

The numeric half does not come from the picture. Both sides are seeded through the SAME
backend routes with the SAME 24 threads and 2 projects (fixed ids, titles and timestamps,
so the two panels render identical text), then the scene bulk-archives three of them from
the UI and reads `/api/chat/threads?include_archived=true` back off the photographed
server. BEFORE cannot archive a selection at all, so that count stays 0 while AFTER moves
to 3. A picture shows a toolbar appeared; that count is what says it works.

Both shots are padded onto a fixed canvas before they leave the scene: `hstack_images`
equalises heights by SCALING, so a one-pixel difference would blow one half up and the
pair would look retouched.

Listings and SQLite rows only: no weights, no GPU, no model download.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import urllib.error
from pathlib import Path

WORKSPACE = Path(os.environ.get("UNSLOTH_WORKSPACE", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from pr_ui_scenes._common import Session, api_get, api_post  # noqa: E402
from studio_test_kit.auth import seed_init_script  # noqa: E402
from studio_test_kit.ui import open_chat  # noqa: E402

try:
    from PIL import Image
except ImportError:  # noqa: BLE001 -- reported at use, not at import
    Image = None

# 900px viewport -> an 868px dialog -> a 620px content panel, which lands near 1:1 in a
# GitHub comment (a 1500px pair renders ~440px per half). The dialog height is
# min(820px, 100dvh-2rem), so 900px of height pins it at 820 on both sides.
VIEWPORT = (900, 900)
CANVAS = (620, 820)

# Untouched by this PR: the control, and the row the new one is inserted after.
CONTROL_ROW = '[data-settings-label="Use chats as training data"]'
MANAGE_ROW = '[data-settings-label="Manage chats"]'

SEED_THREAD_COUNT = 24
# Fixed, so `toLocaleDateString` prints the same string on both halves. 2026-03-02 12:00 UTC.
SEED_BASE_MS = 1_772_452_800_000
SEED_DAY_MS = 86_400_000
SEED_PROJECTS = [
    ("pr8745-project-alpha", "Kernel notes"),
    ("pr8745-project-beta", "Export runs"),
]
# Which seeded chats land in a project, so the Project column is not blank.
SEED_PROJECT_FOR_INDEX = {2: 0, 3: 0, 6: 1}
# Ticked in shot 1. Titles, not indices, so the assertion names what was clicked.
SELECT_TITLES = ["Seeded chat 01", "Seeded chat 02", "Seeded chat 03"]


def _thread_id(index: int) -> str:
    return f"pr8745-thread-{index:02d}"


def _seed(session: Session) -> dict:
    """Put the same chats and projects on both sides, through the backend routes.

    Upsert, and every field written explicitly: these homes are reused across runs, and a
    thread left archived by the previous run's bulk action would make the AFTER count read
    3 before anything was clicked.
    """
    for pid, name in SEED_PROJECTS:
        api_post(session, "/api/chat/projects", {
            "id": pid, "name": name, "instructions": "",
            "createdAt": SEED_BASE_MS, "updatedAt": SEED_BASE_MS,
        }, timeout=60)
    for index in range(SEED_THREAD_COUNT):
        # Descending updatedAt, so groupThreads' sort puts "Seeded chat 01" first.
        stamp = SEED_BASE_MS - index * SEED_DAY_MS
        project_slot = SEED_PROJECT_FOR_INDEX.get(index)
        api_post(session, "/api/chat/threads", {
            "id": _thread_id(index + 1),
            "title": f"Seeded chat {index + 1:02d}",
            "modelType": "base",
            "modelId": "",
            "pairId": None,
            "projectId": SEED_PROJECTS[project_slot][0] if project_slot is not None else None,
            "archived": False,
            "createdAt": stamp,
            "updatedAt": stamp,
        }, timeout=60)
    return _thread_state(session)


def _thread_state(session: Session) -> dict:
    """Thread counts off the photographed server, split by archived flag."""
    threads = api_get(session, "/api/chat/threads?include_archived=true", timeout=120)["threads"]
    mine = [t for t in threads if str(t["id"]).startswith("pr8745-thread-")]
    return {
        "seeded_total": len(mine),
        "seeded_archived": sorted(t["id"] for t in mine if t.get("archived")),
        "seeded_in_project": sorted(t["id"] for t in mine if t.get("projectId")),
    }


def _pad(src: Path, dest: Path) -> Path:
    """Centre `src` on a fixed CANVAS so hstack_images has nothing to rescale."""
    if Image is None:
        raise RuntimeError("Pillow is required to pad the shots onto a fixed canvas")
    with Image.open(src) as img:
        shot = img.convert("RGB")
        canvas = Image.new("RGB", CANVAS, "white")
        # Never crop: an oversized shot is a layout change worth seeing, so widen the
        # canvas rather than cutting the evidence down to fit it.
        if shot.width > CANVAS[0] or shot.height > CANVAS[1]:
            canvas = Image.new("RGB", (max(shot.width, CANVAS[0]),
                                       max(shot.height, CANVAS[1])), "white")
        canvas.paste(shot, ((canvas.width - shot.width) // 2, 0))
        canvas.save(dest)
    return dest


async def _panel(page):
    """The settings dialog's scrolling content column."""
    panel = page.get_by_role("dialog").locator("main > div.overflow-y-auto").first
    await panel.wait_for(state="visible", timeout=60_000)
    return panel


async def _shoot(page, panel, out_dir: Path, name: str) -> Path:
    """Photograph the panel element, scrolled to the top, padded to CANVAS."""
    await panel.evaluate("el => el.scrollTo({top: 0, behavior: 'instant'})")
    await page.wait_for_timeout(1_000)
    raw = out_dir / f"raw_{name}"
    await panel.screenshot(path=str(raw))
    return _pad(raw, out_dir / name)


async def _row_labels(page) -> list[str]:
    rows = page.get_by_role("dialog").locator("[data-settings-label]")
    return [await rows.nth(i).get_attribute("data-settings-label")
            for i in range(await rows.count())]


async def _button_texts(scope) -> list[str]:
    buttons = scope.locator("button")
    out = []
    for i in range(await buttons.count()):
        text = re.sub(r"\s+", " ", (await buttons.nth(i).inner_text()).strip())
        if text:
            out.append(f"{text}{'' if await buttons.nth(i).is_enabled() else ' (disabled)'}")
    return out


async def drive(session: Session, out_dir: Path, label: str,
                **_: object) -> tuple[list[Path], dict]:
    """Photograph the Data panel, then the bulk manager if this build has one."""
    out_dir.mkdir(parents=True, exist_ok=True)
    facts: dict = {"seed": _seed(session)}

    init = seed_init_script(
        type("A", (), {"access_token": session.access_token,
                       "refresh_token": session.refresh_token})(),
        [],
        # The dialog restores its last tab from localStorage, so the panel is already the
        # right one before the explicit tab click below.
        extra_local_storage={"unsloth_settings_active_tab": "data"},
    )
    shots: list[Path] = []
    async with open_chat(session.base_url, init_scripts=[init],
                         viewport=VIEWPORT, headless=True) as sp:
        page = sp.page
        # /settings opens the modal in beforeLoad and redirects home, so the dialog is the
        # surface; there is no standalone settings page to screenshot.
        await page.goto(f"{session.base_url}/settings", wait_until="domcontentloaded")
        tab = page.locator('[data-testid="settings-tab-data"]').first
        await tab.wait_for(state="visible", timeout=60_000)
        await tab.click()
        panel = await _panel(page)

        # The control, asserted rather than assumed: everything below depends on the Data
        # tab having actually rendered, and an empty panel photographs cleanly.
        control = page.locator(CONTROL_ROW).first
        await control.wait_for(state="visible", timeout=60_000)
        facts["control_row_present"] = await page.locator(CONTROL_ROW).count()
        facts["control_row_text"] = re.sub(
            r"\s+", " ", (await control.inner_text()).strip())
        # The rows fetch their own counts on mount; a shot taken before those land shows
        # an unpopulated shell on BOTH sides.
        await page.wait_for_timeout(5_000)

        facts["data_row_labels"] = await _row_labels(page)
        facts["manage_chats_row_present"] = await page.locator(MANAGE_ROW).count()
        shots.append(await _shoot(page, panel, out_dir, f"{label.lower()}_data_tab.png"))

        if facts["manage_chats_row_present"]:
            manage_row = page.locator(MANAGE_ROW).first
            facts["manage_chats_row_text"] = re.sub(
                r"\s+", " ", (await manage_row.inner_text()).strip())
            await manage_row.locator("button").filter(
                has_text=re.compile(r"^Manage$")).first.click()

            # assert_showing would pass on the Data heading, which is present on the main
            # page too, so the subpage is proved by its own table header instead.
            header = panel.get_by_text("Date created", exact=True).first
            await header.wait_for(state="visible", timeout=60_000)
            counter = panel.get_by_text(re.compile(r"^\d+ chats?( selected)?$")).first
            await counter.wait_for(state="visible", timeout=60_000)
            facts["manage_counter_at_rest"] = (await counter.inner_text()).strip()
            # Anchored on the select-all checkbox rather than a class match: the toolbar
            # is the only wrapping row that contains it, and a bare `div.flex-wrap` would
            # also match a SettingsRow if this subpage ever grows one.
            select_all = panel.get_by_role("checkbox", name="Select all chats").first
            await select_all.wait_for(state="visible", timeout=60_000)
            toolbar = select_all.locator(
                "xpath=ancestor::div[contains(@class,'flex-wrap')][1]")
            facts["manage_toolbar_at_rest"] = await _button_texts(toolbar)
            facts["manage_visible_rows"] = await panel.get_by_role(
                "checkbox", name=re.compile(r'^Select "Seeded chat ')).count()
            show_more = panel.locator("button").filter(
                has_text=re.compile(r"^Show more \(")).first
            facts["manage_show_more"] = (
                (await show_more.inner_text()).strip() if await show_more.count() else None)

            for title in SELECT_TITLES:
                box = panel.get_by_role("checkbox", name=f'Select "{title}"').first
                await box.scroll_into_view_if_needed()
                await box.click()
                # Assert the tick landed. A Radix checkbox click that misses leaves the
                # toolbar disabled, and a disabled toolbar photographs perfectly.
                await page.wait_for_timeout(200)
                if await box.get_attribute("aria-checked") != "true":
                    raise RuntimeError(f"ticking {title!r} did not check its box")
            await page.wait_for_timeout(800)
            facts["manage_counter_selected"] = (await counter.inner_text()).strip()
            facts["manage_toolbar_selected"] = await _button_texts(toolbar)
            shots.append(await _shoot(page, panel, out_dir,
                                      f"{label.lower()}_manage_selected.png"))

            # The measurement: a bulk archive driven entirely from this toolbar.
            await toolbar.locator("button").filter(
                has_text=re.compile(r"^Archive$")).first.click()
            await page.wait_for_timeout(6_000)
            facts["manage_counter_after_archive"] = (await counter.inner_text()).strip()
        else:
            facts["manage_chats_row_text"] = None
            facts["manage_counter_at_rest"] = None
            facts["manage_toolbar_at_rest"] = None
            facts["manage_visible_rows"] = None
            facts["manage_show_more"] = None
            facts["manage_counter_selected"] = None
            facts["manage_toolbar_selected"] = None
            facts["manage_counter_after_archive"] = None
            # No row to click, so shot 1 is the panel again. The repeat is the finding.
            shots.append(await _shoot(page, panel, out_dir,
                                      f"{label.lower()}_manage_selected.png"))

    try:
        facts["state_after_bulk_archive"] = _thread_state(session)
    except urllib.error.HTTPError as exc:
        facts["state_after_bulk_archive"] = f"http {exc.code}"

    print(f"[{label}] {json.dumps(facts)}", flush=True)
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
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    s = studio_session(a.url, a.home, a.password)
    print(asyncio.run(drive(s, a.out, a.label)))

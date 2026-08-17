# PR 8557 UI evidence

Disposable orphan branch. It holds the before/after Studio evidence for
[unslothai/unsloth#8557](https://github.com/unslothai/unsloth/pull/8557) and one
branch-scoped workflow that republishes it as the `pr8557-evidence` artifact. No
source, no other workflow, no history: delete the branch once the PR closes.

## What was photographed

Two isolated Studio installs, one at the PR's merge base `c3230a749` and one at its
head `79b6fccb5`, each built by `install.sh --local` from its own worktree so the
frontend bundle really is that tree's. Both were driven through the same scene.

The scene writes one MCP server row with a **fixed** id, `9f2c41ab7de05613`, and the
display name `GitHub Issues`, then stores one assistant turn calling
`mcp__9f2c41ab7de05613__create_issue` alongside a non-MCP `web_fetch` control. The id
is fixed on purpose: `routes/mcp_servers.py` mints it as `uuid.uuid4().hex[:16]`, and
two random ids would have made the tool name itself differ between the sides, so the
pair would have proved nothing about the label.

Both sides receive byte-identical input, `provenance.mcp_server` included. The base
is handed the display name and ignores it; only the head reads it. That value is not
taken on trust: `facts.json` also records what each install's own
`core/inference/tool_loop_controller` returns for the same tool name against the same
sqlite row.

## Files

| file | what it is |
| --- | --- |
| `evidence/pr8557_pair_00_tool_cards.png` | the tool-call fallback cards, MCP call above the `web_fetch` control |
| `evidence/pr8557_pair_01_details_sheet.png` | the response details sheet, Tools > Enabled and Called |
| `evidence/pr8557_pair_02_markdown.png` | the exported conversation markdown's tool call headings |
| `evidence/before_conversation.md` | the markdown the base install actually downloaded |
| `evidence/after_conversation.md` | the markdown the head install actually downloaded |
| `evidence/facts.json` | every reading, per side, plus both SHAs |
| `verify_pr8557_evidence.py` | re-asserts all of the above |

## The readings

| | base `c3230a749` | head `79b6fccb5` |
| --- | --- | --- |
| card | `Used tool: 9f2c41ab7de05613 · create_issue` | `Used tool: GitHub Issues · create_issue` |
| sheet, Called | `MCP: 9f2c41ab7de05613__create_issue, Fetch` | `MCP: GitHub Issues · create_issue, Fetch` |
| markdown | ``**tool call:** `mcp__9f2c41ab7de05613__create_issue` `` | ``**tool call:** `GitHub Issues · create_issue` `` |
| `status_for_tool` | `Calling: mcp__9f2c41ab7de05613__create_issue` | `Calling: GitHub Issues · create_issue` |
| `mcp_display_parts` | absent | `("GitHub Issues", "create_issue")` |

Unchanged on both sides, which is the control: the `web_fetch` card
(`Used tool: web_fetch`), the sheet's `Enabled` row (`Fetch, MCP`), the `Fetch` entry
in `Called`, the `web_fetch` markdown heading, and the tool-call heading count (2).

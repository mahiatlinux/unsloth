# PR 8951 UI evidence

Disposable branch. It carries the before/after Studio evidence for
[unslothai/unsloth#8951](https://github.com/unslothai/unsloth/pull/8951) and nothing else,
so delete it once that PR is closed.

`evidence/` holds the pair produced by `scripts/pr_ui_diff.py --pr 8951`: two isolated
Studio installs, one built at the PR's merge base `6f443b5cc` and one at its head
`b8f1d669c`, each under its own `UNSLOTH_STUDIO_HOME`, both launched with the default
`127.0.0.1` bind and driven through the same scene.

| File | What it is |
|---|---|
| `pr8951-before-after-settings-section.png` | labelled `BEFORE \| AFTER` of Settings > API keys at rest |
| `pr8951-before-after-lan-started.png` | the same panel after the `Start` button is pressed |
| `before-api-keys-panel.png`, `before-api-keys-panel-started.png` | the raw merge-base halves |
| `after-api-keys-panel.png`, `after-api-keys-panel-started.png` | the raw head halves |
| `facts.json` | the scene's API readings and socket probes for both sides, and the SHAs they came from |
| `SHA256SUMS.txt` | generated in CI over the files above |

The two merge-base shots are identical because that build has no `Start` button to press.

`.github/workflows/pr8951-evidence.yml` runs `verify_evidence.py` over the bundle and
uploads it as the `pr8951-evidence` artifact.

# PR 8514 evidence (disposable)

Staging branch for UI evidence on upstream [unslothai/unsloth#8514](https://github.com/unslothai/unsloth/pull/8514),
"fix chat search dialog stutter on open". Not code, not for merge. An orphan commit, so it
carries nothing but the evidence and the one workflow that packages it.

Shot from two isolated Studio installs, merge base `34a119764` vs head `aa40cace3`, driven
through the same scene: a seeded 60-chat history, Ctrl+K, then the filter, then a close and
reopen, at 1280x900.

`.github/workflows/pr8514-evidence.yml` re-checks the numbers quoted on the PR against the
files in `evidence/`, converts the recorded webms to gif, and uploads the lot as the
`pr8514-evidence` artifact.

Read `evidence/NOTES.md` for the method and, more importantly, for what this evidence
deliberately does not claim: no wall-clock or frame-rate figure, because neither this box
nor the runner had controlled load. Every number is layout geometry.

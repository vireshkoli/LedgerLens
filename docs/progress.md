# Progress

Update this at the end of every task, so work can restart from here after a conversation summary or in a new session.

**Current task:** none. M0-2 is done and on `main`.

**Next task:** M0-3, CI. Branch from `main`.

## Open questions

- O9: you report your OpenAI and Anthropic key credit before V3-1.

## Hours

Build time is session wall-clock, so it won't match a human developer's hours. Review time is what you report.

| Task | Status | Planned h | Actual build h | Your review h | Notes |
| --- | --- | --- | --- | --- | --- |
| M0-1 | Done | 3.5 | 0.1 | | Refused in real commits: a fake token, a PDF, a renamed PDF, FinanceBench by name and by content, a private-tier file. The first version blocked its own source, so a regression test covers that |
| M0-2 | Done | 1.5 | 0.4 | | `make dev` serves the API and web inside the 6 GiB limit. All six services used 1,106 MiB when idle. A fresh clone passed setup, lint, test, dev and wipe |
| M0-3 | Not started | 2 | | | Wire `check_forbidden_files.py` into CI, including added-then-removed files in history. CI needs Node 26, Buildx and Docker Compose |
| M0-4 | Not started | 3.5 | | | |
| M0-5 | Not started | 3 | | | |
| M0-6 | Not started | 2 | | | |
| M0-7 | Not started | 2 | | | |
| M0-8 | Not started | 2.5 | | | |
| M0-9 | Not started | 1.5 | | | |

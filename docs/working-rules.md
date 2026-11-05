# LedgerLens working rules

Start every session by reading `docs/progress.md` and the latest entries in `docs/task-log.local.md`. Do the same after a conversation summary, and trust those files over the summary. Progress says which task is current, what comes next and what's open. The log records what each finished task did and learned. The approved plan is `docs/plan.local.md`, the brief is `PROJECT_BRIEF.md`, and host details are in your local notes. The log, plan, brief and notes are local only and never go in Git.

## Sessions

- Work through the tasks in order in one long session, one task at a time. A new session is fine whenever the user wants one, because the files hold everything needed to restart.
- When a task's acceptance test passes, add its entry to `docs/task-log.local.md`, update `docs/progress.md` and stop until the user says to continue.
- Keep log entries short. Record what the code can't show: decisions, problems and their fixes, and anything a later task needs. Never put secrets in the log.
- Read only what the current task needs. Look up a task's row in the plan instead of reading the whole plan.
- Don't run multi-agent workflows unless asked.
- At each milestone checkpoint, give the change summary, actual vs planned hours, the walkthrough link, three questions and a list of doubts. Then wait for approval.

## Spending

- ₹0 until the cost gate (V3-1). That covers cloud and hosted LLM calls.
- Before any paid resource, GPU job or action over ₹200: show the estimate and wait for a yes.
- Any evaluation, GPU job or batch over 100 LLM calls prints an estimate and needs `--yes`.
- All hosted LLM calls go through `LLMClient`, which enforces the monthly cap.

## Results

- Never invent a number. Everything in a README, report or table comes from a script reading `runs/`. If a run hasn't happened, say "not yet run".
- Don't guess APIs, versions, prices or licences. Read the official source and pin what you used.

## Data

- Never commit PDFs, FinanceBench files or anything from the private tier. A hook and CI block them. Don't bypass them.
- Private-tier files stay on the Mac: never on the A40, never in the cloud, never sent to a hosted LLM, never in a public demo.
- Respect SEC fair access: a declared User-Agent and at most 10 requests per second.

## Secrets

- Secrets live in `.env`, which is ignored. Commit only `.env.example`.
- If a secret is ever committed, stop, tell the user and rotate it.

## Compute

1. Never edit files on a remote machine. Remote copies are disposable.
2. Every remote run uses a committed Git version. Syncing uncommitted work is allowed only for runs labelled `exploratory`.
3. Remote jobs must survive the Mac sleeping: run them in `tmux`, with logs written to files. The one exception is hosted evaluation runs, which resume from recorded state.
4. Checkpoint often and resume automatically.
5. Small artifacts return to `runs/<id>/`. Large ones stay remote, with a pointer file (location, checksum, size).
6. Build the environment from the lockfile everywhere, and record GPU, driver, CUDA and torch versions in every run.
7. The Mac is ARM64. Build cloud images for `linux/amd64`.
8. No heavy jobs on the Mac: anything over about 30 minutes of sustained compute goes to the A40 or the cloud.
9. The A40 host is shared. Check free GPU memory and disk before every job. If memory isn't enough, tell the user which GPU is needed and for how long. Never stop or touch running servers. Never store API keys there.

## Code

- Python 3.14, fully type-hinted public functions, `ruff` and `mypy` strict.
- Comments explain why, not what. Every public function has a docstring. No dead code and no commented-out blocks.
- No LangChain, LlamaIndex, LangGraph or similar frameworks anywhere in the core path.
- Tests come with each task, and core packages stay at 85% coverage or above.

## Version control

- One branch per task, named like `m0-1-repo-skeleton`. Small commits with conventional-commit messages.
- Everything reaches `main` through a pull request, merged with `gh pr merge --rebase` once the required checks pass. A ruleset refuses direct pushes, and nobody can bypass it.
- A pushed branch is public even if CI fails, so the pre-commit hook is the only thing that stops a file before it's published.
- Tag each milestone release.

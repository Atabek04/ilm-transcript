---
name: spec
description: Spec-driven development for ilm-transcript (Python). Enforces 3-gate flow (requirements → design → tasks → implement) with PR as unit of delivery. Invoke proactively when the user is about to build a new module, add a feature, or says "/spec", "write spec", "plan module", "design this", "break into tasks", "implement this", "add feature", or shows intent to start coding something new without a spec. Adapted from mutqin/platform for Python/pytest/ruff.
---

# Spec Orchestrator (Python)

Routes `/spec` subcommands to the correct phase. Adapted for Python — no Maven, no npm, no Next.js. Uses `pytest`, `ruff`, `pip`.

## Parse `$ARGUMENTS`

| Pattern                         | Action                                                                                                     |
|---------------------------------|------------------------------------------------------------------------------------------------------------|
| `create <name> "<description>"` | Write `docs/specs/<name>/requirements.md`                                                                  |
| `review <name>`                 | Staff-engineer review of latest spec doc in `docs/specs/<name>/`                                           |
| `design <name>`                 | Write `docs/specs/<name>/design.md` (module layout, function signatures, I/O contracts)                    |
| `tasks <name>`                  | Write `docs/specs/<name>/tasks.md` — PR Plan table, each PR a bundle of `[ ]` tasks                        |
| `implement <name>`              | Auto-select first PR with any `[ ]` task. All done → "No tasks left for `<name>`."                         |
| `implement <name> PR<N>`        | Implement that PR (all tasks in it)                                                                        |
| `implement <name> <task-id>`    | Resolve the task's PR, implement the full PR                                                               |
| `status <name>`                 | Report which phase files exist in `docs/specs/<name>/`                                                     |
| `list`                          | Scan `docs/specs/*/` and show status for each module                                                       |

> **KEY RULE — PR is the unit of delivery.** Always implement a full PR, never a single isolated task.

## Status Report Format

```
Module: <name>
├── Requirements: ✅ / ❌
├── Design:       ✅ / ❌
├── Tasks:        ✅ (3/8 implemented) / ❌
└── Next: `/spec <next-phase> <name>`
```

## Implementation Workflow

### Phase 1: Resolve target PR & prerequisites

1. **Resolve target:**
   - Read `docs/specs/<name>/tasks.md` — locate **PR Plan** table.
   - No PR specified → first PR with any `[ ]` task. All `[x]` → stop.
   - Task-id specified → resolve its PR, implement full PR.
   - Check PR dependencies — blockers incomplete? List them and stop.

2. **Parallel context load (one batch):**
   - Read `requirements.md`, `design.md`, `tasks.md`.
   - `Glob` existing module paths (`convert.py`, `transcribe.py`, etc.).
   - `Grep` for patterns (logging format, type hints style, existing constants).
   - `Bash`: `git status`, `git branch`.
   - **No subagents yet — direct tools only.**

### Phase 2: Plan — HARD STOP before any code

3. **Invoke `EnterPlanMode`:**
   - Inside plan mode: Read, Grep, Glob, Bash only. **Never nest subagents** — doubles token cost, slows execution.
   - Read every file the PR touches: modules, tests, `requirements.txt`, `CLAUDE.md`, `SPEC.md`.
   - Verify library APIs via docs — training data goes stale (`faster-whisper`, `yt-dlp` change often).
   - Plan: files to create/modify, function signatures, key decisions, branch name.
   - **Do not write a single line of code until user approves.**
   - Call `ExitPlanMode`.

### Phase 3: Implement

4. **Branch setup — always from `main`:**
   ```bash
   git checkout main && git pull --prune
   git checkout -b feat/<module>-<brief-task-description>
   ```
   If uncommitted work blocks checkout, stash first.

5. **Install dependencies explicitly before writing code.**
   - If task calls for a library, install it immediately — never inline-reimplement, never substitute.
   - Pin version in `requirements.txt`:
     ```bash
     pip install <pkg>==<version>
     # then add exact line to requirements.txt
     ```
   - The spec was written against that library's specific API.

6. **Write code strictly scoped to task deliverables.**
   - No speculative abstractions. Name the stdlib idiom before inventing a pattern.
   - Follow `CLAUDE.md` project rules: type hints, `logging` not `print`, UTF-8 everywhere, idempotent runs, `encoding="utf-8"`.
   - Python 3.10+. Functions over classes unless necessary.

7. **Write tests for every acceptance criterion.**
   - `tests/test_<module>.py`, `pytest` style.
   - Cover: happy path, Arabic-script preservation, idempotency, missing-dep error messages.

### Phase 4: Verify — must pass before PR

8. **Syntax + tests + lint — zero warnings:**
   ```bash
   python -m py_compile $(git diff --name-only main -- '*.py')
   pytest -q
   ruff check .
   ruff format --check .
   ```
   Anything fails → fix before proceeding. Never open PR from broken state.

9. **Self-review the diff:**
   - `git diff main` — read every line as reviewer, not author.
   - Check: matches acceptance criteria? Any hardcoded values, dead code, unused imports, `print()` instead of `logging`? Arabic text mangled?
   - Fix issues. Re-run tests + lint after fixes.
   - If any file looks overbuilt → invoke `/simplify`.

### Phase 5: Commit, PR, watch CI

10. **Mark tasks `[x]` in `tasks.md`.** All tasks in the PR — not just one.

11. **Commit:**
    - Format: `<type>(<scope>): <description>` — max 72 chars, imperative, lowercase.
    - Types: `feat`, `fix`, `test`, `refactor`, `docs`, `chore`, `perf`.
    - Scope: module name (`convert`, `transcribe`, `output`) or area (`cli`, `ci`).
    - **Never include AI attribution.**

12. **Open PR via `gh pr create`:**
    - Title matches commit.
    - Body: `## What` (1–3 bullets) + `## Why` (links to spec task) + `## Test plan` (`[x]` for done, `[ ]` for post-merge manual).
    - Output URL plain: `https://github.com/<owner>/ilm-transcript/pull/NN` — terminal-clickable.

13. **Watch CI (if configured).** If no CI yet, skip. Otherwise `Monitor` until terminal state:
    ```bash
    until st=$(gh pr checks <N> --json state -q '.[0].state' 2>/dev/null); [[ "$st" == "SUCCESS" || "$st" == "FAILURE" ]]; do sleep 20; done; echo "CI: $st"
    ```
    On FAILURE: `gh run view <RUN_ID> --log-failed | tail -80`, fix root cause (not symptom), push, re-monitor. **Every CI failure = missing rule.** Add to `CLAUDE.md` so the class of error can't recur.

14. **Report next steps:** unblocked tasks, suggested next PR.

### Phase 6: After merge

```bash
git fetch --prune && git checkout main && git pull && git branch -d <old-branch>
```

## Rules

### Planning discipline
- **Never nest subagents inside `EnterPlanMode`.** Claude does the thinking inside plan mode — not a subagent. Redundant research doubles cost.
- **Parallel context gathering before plan mode.** Batch spec reads, globs, greps, git status in one message.
- **Plan mode isolation.** Only discover/read existing code. No context-switch to other agents/skills until `ExitPlanMode` → approval.

### Implementation discipline
- **Return-after-merge check.** New session starting with "implement Tx": check current branch first. Stale merged branch → main, pull, prune, fresh branch before code.
- **Branch naming:** `feat/<module>-<brief>` — one branch per PR.
- Never skip phases. Requirements → Design → Tasks → Implement.
- Missing phase file → tell user which command to run first.
- Build + tests + lint must pass before PR. Never open PR from broken state.
- Self-review diff before PR. You are the first reviewer, not the last.
- Mark all PR tasks `[x]` in `tasks.md` after implementation.

### No overengineering (hard rule from `CLAUDE.md`)
- Implement exactly what the task requires. No extra abstraction, no speculative generalization, no "while I'm here" refactors.
- Before introducing a pattern (factory, strategy, decorator) — verify the task needs it. A pattern serving one use case is just indirection.
- Name the existing stdlib/idiom that already solves the problem before inventing a new one.
- Three similar lines beats a premature abstraction.

### Python-specific carryovers
- **UTF-8 always** — all file writes with `encoding="utf-8"`. Arabic text must never mangle.
- **`logging` not `print`** — format `[HH:MM:SS] message`.
- **Type hints on all signatures.** Docstrings on public functions (one-liner fine).
- **Idempotent runs** — check output exists before redoing work. `--force` flag to override.
- **Fail loudly with actionable errors** — e.g. `"ffmpeg not found — install with: brew install ffmpeg"`, not a traceback.
- **No new deps beyond the spec.** Stdlib first. If a dep is needed, pin it and justify in the PR body.

### Scope discipline for this project
- `bot.py` (Phase 4) is out of scope until explicitly asked. Do not add `python-telegram-bot`, `python-docx`, `reportlab` to `requirements.txt`.
- No GPU code, no web server, no DB. Personal CLI tool.

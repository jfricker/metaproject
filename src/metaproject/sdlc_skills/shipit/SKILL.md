---
name: shipit
description: Ship a finished branch end to end — run the quality gate, flag unrelated changes, fast-forward merge into main, push, deploy and verify live, then clean up the worktree and branches. Use when the user says "shipit", "ship it", "ship this branch", "merge and deploy", "merge, push and clean up", or the work is tested and approved and only the landing is left. Not for writing or testing code — that is implement-plan and execute-tests.
---

# shipit

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Lands a finished branch: gate, review what ships, merge, push, deploy, verify, clean up.
This skill owns branch shipping; `wrapup` (cycle-document archive) delegates its
worktree and branch cleanup here.

## When to use

- The work is implemented, tested, and approved, and the operator wants it on `main`
  (and live, if the project deploys).
- Not for unfinished work — send that back to `implement-plan` / `execute-tests`.

## Process

Run the steps in order. Stop at the first failure and report it; never skip a step to
keep going.

1. **Gate.** Run the project's quality gate exactly as `AGENTS.md` / the `Makefile`
   define it (for this family of projects: `make format && make lint && make test`;
   include `make build` if AGENTS.md lists it). On any failure, stop and show the
   output. Do not ship red.
2. **Review what ships.** Compare the branch with `main`
   (`git log --oneline main..HEAD`, `git diff --stat main...HEAD`). List the commits and
   files, and flag anything that does not belong to this work: held-back dependency
   upgrades, lockfile churn, unrelated refactors, stray debug files, version bumps nobody
   asked for. Ask the operator to confirm or drop flagged items before continuing.
3. **Merge.** Fast-forward only. Update `main` (`git fetch origin`), rebase the branch on
   `origin/main` if it is behind, rerun the gate if the rebase changed anything, then
   `git merge --ff-only <branch>` in the main checkout and `git push origin main`. If a
   fast-forward is impossible or the push is rejected, stop — never force-push and never
   create a merge commit unasked.
4. **Deploy (if the project deploys).** Detect the target, in this order:
   - a `deploy` target in the `Makefile` (`make deploy`);
   - a Cloudflare project (`wrangler.jsonc` / `wrangler.toml`) — prefer the Cloudflare
     MCP tools; ask before falling back to `wrangler` (Python Workers use `pywrangler`);
   - a PM2 app (`ecosystem.config.*` or `pm2 list` naming the project) —
     `pm2 reload <app>`.
   If none is found, say "no deploy target detected" and skip to step 6. If more than one
   matches, ask which to use.
5. **Verify live.** Probe the deployed service: `curl -fsS <url>/health` if it exposes
   one, otherwise `curl -fsSI <url>` and expect a 2xx/3xx. Report the URL and status. On
   failure, stop and report; do not clean up the branch until the operator decides on a
   rollback.
6. **Clean up.** Remove the worktree and delete the branch locally and on the remote:
   - `git worktree remove <path>` then `git worktree prune` (these write under
     `.git/worktrees`, so run them outside the sandbox);
   - `git branch -d <branch>` and `git push origin --delete <branch>`.
   Use `-d`, not `-D`: if git says the branch is unmerged, stop. Do nothing if the work
   was done on `main` directly. Leave other branches and worktrees alone.
7. **Report.** One short summary: what merged (commit range), gate result, flagged items
   and how they were resolved, deploy target and live URL with the verification result,
   what was cleaned up, and a list of manual-verification items (anything not checkable
   by command, such as visual or interactive behaviour).

## Stop conditions / human gate

- Gate failure, unconfirmed unrelated changes, non-fast-forward merge, rejected push,
  failed live verification, or an unmerged-branch warning: stop and ask.
- Never force-push, never `--no-verify`, never delete a branch that is not merged into
  `main`.
- Do not edit cycle documents (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`,
  `docs/PLAN.md`, `docs/STATE.md`); archiving them is `wrapup`'s job.

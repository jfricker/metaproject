---
name: shipit
description: Ship a finished branch end to end — run the quality gate, flag unrelated changes, fast-forward merge into main, push, deploy and verify live, then clean up the worktree and branches. Use when the user says "shipit", "ship it", "ship this branch", "merge and deploy", "merge, push and clean up", or the work is tested and approved and only the landing is left. Not for writing or testing code — that is implement-plan and execute-tests.
---

# shipit

> **Precondition.** This project must be metaproject-managed: the nearest `.metaproject.json`
> (this directory or an ancestor) and `metaproject` on `PATH`. If either is missing, stop and tell the
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
   matches, ask which to use. Then classify the target (see "Production or preview"). A
   preview or staging deploy goes straight ahead; a PRODUCTION deploy must first pass
   step 4a.
   4a. **Zero-downtime plan (production only).** Write exactly five lines, then STOP:
      1. how the new version starts alongside the old one (new Worker version / gradual
         deployment, `pm2 start` under a new name, second release directory, ...);
      2. the health check that will be run (URL and expected status);
      3. the swap step (the exact command that moves traffic);
      4. the exact rollback command, copy-pasteable;
      5. how downtime will be measured (poll the health URL about once a second across the
         swap and count failed probes).
      Do not run any deploy command until the operator replies with an explicit OK in chat.
      A silence, a thumbs-up on something else, or an OK to the merge is not an OK to
      deploy. If the operator changes the plan, rewrite the five lines and ask again.
      After the OK, execute the plan exactly as written while polling the health URL, and
      carry the measured downtime (failed probes, longest gap, or "none observed") into
      step 5 and the report. If the plan cannot be followed, stop and ask.
5. **Verify live.** Probe the deployed service: `curl -fsS <url>/health` if it exposes
   one, otherwise `curl -fsSI <url>` and expect a 2xx/3xx. Report the URL and status. On
   failure, stop and report; do not clean up the branch until the operator decides on a
   rollback (for a production deploy, offer the rollback command from the plan).
6. **Clean up.** Remove the worktree and delete the branch locally and on the remote:
   - `git worktree remove <path>` then `git worktree prune` (these write under
     `.git/worktrees`, so run them outside the sandbox);
   - `git branch -d <branch>` and `git push origin --delete <branch>`.
   Use `-d`, not `-D`: if git says the branch is unmerged, stop. Do nothing if the work
   was done on `main` directly. Leave other branches and worktrees alone.
7. **Report.** One short summary: what merged (commit range), gate result, flagged items
   and how they were resolved, deploy target and live URL with the verification result,
   the downtime observed (production deploys), what was cleaned up, and a list of manual-verification items (anything not checkable
   by command, such as visual or interactive behaviour).

## Production or preview

No new configuration is introduced; classify from what the project already declares, and
when in doubt treat the target as production.

- **Preview/staging:** a Makefile target named `deploy-preview`, `deploy-staging`,
  `preview` or `staging`; a wrangler invocation with `--env` naming `preview`, `staging`,
  `dev` or `test`, or a version upload that does not go live (`wrangler versions upload`);
  a PM2 app whose name ends in `-staging`, `-preview` or `-dev`.
- **Production:** `make deploy`, `deploy-prod`, `deploy-production`, `prod`; a wrangler
  deploy with no `--env` or `--env production`; any other PM2 app.
- If the classification is ambiguous, ask the operator rather than guessing preview.

## Stop conditions / human gate

- A production deploy never starts without the five-line plan and the operator's explicit
  OK; this gate applies even when the operator has already approved the merge.

- Gate failure, unconfirmed unrelated changes, non-fast-forward merge, rejected push,
  failed live verification, or an unmerged-branch warning: stop and ask.
- Never force-push, never `--no-verify`, never delete a branch that is not merged into
  `main`.
- Do not edit cycle documents (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`,
  `docs/PLAN.md`, `docs/STATE.md`); archiving them is `wrapup`'s job.

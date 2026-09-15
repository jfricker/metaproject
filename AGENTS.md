# AGENTS.md

## Dependency on metaproject

This repo requires `metaproject` **≥ 0.7.0** on `PATH`. metaproject owns every document
template used below (`intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`,
`ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`, `AGENTS.md`,
`README.md`, `CLAUDE.md`, `.gitignore`, `HANDOFF.md`) from its central template store;
this repo carries none of its own. A missing document is created with
`metaproject backfill <file>`, never written from scratch.

Merge order when this repo's changes depend on new metaproject templates or commands:
metaproject merges first (and its version bump lands on its `main`), the operator
refreshes `~/.metaproject/templates` from the merged store by hand, and only then does
sdlc-skills merge and rely on the new template shapes or commands.

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Testing instructions

## Process
This process is based on https://claude.com/blog/the-ai-native-sdlc-playbook with modifications. This document adds to the playbook and merges ideas. It doesn't supersede the playbook unless explicitly stated.

### HANDOFF.md
 When work is interrupted before completion, create a HANDOFF.md to capture the state of the work and any other information needed to resume the work or hand it off to another agent at another time.

### STATE.md
 Maintain a running list of all tasks and their status. Update it as tasks are completed. Format the list as a checklist with a box, task number and a task description.

### intent.md
 intent.md is a source of truth for proposed changes to the system. Read it when instructed to and mark it complete after all work is tested and merged. Move the file to docs/archive/ after confirmation from operator and rename it `YYYY-MM-DD-<title>|intent.md`. 

### spec.md
 The agent will be instructed to create a design and requirements spec from the intent.md.

### plan.md
 The agent will be instructed by the operator to create an implementation plan based on the spec.md and any design artifacts. 

### design.md
 The agent will be instructed to create a technical design from an approved spec.md — affected components, data flow, alternatives, trade-offs — which plan.md then consumes alongside spec.md.

### Pull requests are optional
 A cycle may land as a PR or be committed straight to `main`, operator's choice. `wrapup` asks the operator which happened for the cycle it's closing rather than assuming either way, and won't archive/reset until the operator confirms the work is actually complete and committed.

### ARCHITECTURE.md
 A long-lived, root-level index that never resets between cycles. `wrapup` updates it at the end of every cycle: an entry in its cycle index linking to that cycle's archived spec.md/design.md, a one-line summary, and (when the cycle changed structure) an update to its mermaid diagram(s). Over time ARCHITECTURE.md becomes the sum of every cycle's specifications plus the on-the-fly decisions and choices made along the way — read it before `generate-design` to avoid re-deriving context that's already settled.

### docs/DESIGN-INVARIANTS.md and docs/VERIFIED-FACTS.md
 Long-lived, append-only companions to STATE.md's "Design invariants (regression guards)" and "Verified facts (do not re-investigate)" sections. STATE.md itself resets to blank at the end of every cycle (`wrapup`), so before it does, `wrapup` appends whatever those two sections hold — dated and linked to the cycle's archive — onto these two files instead of letting the knowledge disappear. Read them at the start of `generate-spec`/`generate-design`/`generate-plan` so a fact verified in one cycle doesn't get re-investigated in the next.

### STATE.md's "Open items carried into plan.md"
 Before `wrapup` resets STATE.md, it resolves this section with the operator first — for each item, showing its own assessment of why the item is still open, then asking the operator to discard it, carry it forward into the next `intent.md`'s Open questions, or send the cycle back to `implement-plan` because it isn't actually finished. A single "return to implement-plan" halts the whole wrapup before anything is archived or reset.

### Archive layout
 `wrapup` moves a completed cycle's `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md` and (if present) `HANDOFF.md` into `docs/archive/YYYY-MM-DD-<slug>/`, after appending STATE.md's Design invariants and Verified facts to the long-lived docs above.

# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Testing instructions
- Run `make check` before every commit.
- Use `pytest` for all new tests.

## Process
This process is based on the AI-native SDLC playbook with modifications.

### STATE.md
 Maintain a running list of all tasks and their status.

## Release process
Tag the release, then run `make publish`. Never publish from a dirty worktree.

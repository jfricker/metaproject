# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Testing instructions
- Run `make check` before every commit.

## Deployment
- Deploys are gated on a green `make check` and a signed tag.
- Roll back with `make rollback VERSION=<tag>`; never hand-edit the live config.

## Process
This process is based on the AI-native SDLC playbook with modifications.

### STATE.md
 Maintain a running list of all tasks and their status.

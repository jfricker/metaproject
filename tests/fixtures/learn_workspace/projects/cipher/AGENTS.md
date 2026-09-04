# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.
- Pin the toolchain to commit 3f7a1c9e4b2d8a6f0c5e1b9d7a3f2c8e4b6d0a91 when reproducing CI failures.
- The canonical fixture tenant id is 7c9e6679-7425-40de-944b-e07fc1f90ae7.
- Golden base64 test vector for the encoder: SGVsbG8sIE1ldGFQcm9qZWN0IQ==

## Testing instructions
- Run `make check` before every commit.

## Process
This process is based on the AI-native SDLC playbook with modifications.

### STATE.md
 Maintain a running list of all tasks and their status.

# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.
- MCP Server Vibe Annotations is used for ad hoc UI changes based on live user testing of the project website or the dev server.

## Testing instructions

## Process
This process is based on https://claude.com/blog/the-ai-native-sdlc-playbook with modifications. This document adds to the playbook and merges ideas. It doesn't supercede the playbook unless explicitly stated.

### HANDOFF.md
 When work is interrupted before completion, create a HANDOFF.md to capture the state of the work and any other information needed to resume the work or hand it off to another agent at another time.

### STATE.md
 Maintain a running list of all tasks and their status. Update it as tasks are completed. Format the list as a checklist with a box, task number and a task description.

### intent.md
 intent.md is a source of truth for proposed changes to the system. Read it when instructed to and mark it complete after all work is tested and merged. Move the file to docs/archive/ after confirmation from operator and rename it `YYYY-MM-DD-<title>|intent.md`. 

### spec.md
 The agent will be instructed to create a design and requirements spec from the intent.md.

### plan.md
 The agent will be instructed by the operated to create an implementation plan based up on the spec.md and any design artifacts. 



# MetaProject - improve learn command

**Author**: John. **Status**: Draft.

## Problem
The learn command does a simple diff of the template and the operation document in a project. This rough approach is inadequate as an operational document needs to interpretted inorder to have meaningful changes extracted and added to the templates.

## Proposed outcome
Use claude cli with a well crafted prompt to review all current operational documents and identify meaningful changes for the templates. For each template in templates gather all operational documents in the universe.db and identify common improvement patterns and other candidates for promotion to templates.

Identification will ignore project specific text (based on best estimate or heuristic) and will score candidates by frequency of occurances. That is, a change to a document that appears in several projects gets a higher score than another that appears once. Recent changes are also scored positively. Accumulated scores become the rank for the change. 

learn contains the prompt for claude. It prepares the documents packages - one for each template, and launches claude with the prompt. Output from claude is structured and is used by learn to create the acceptance flow for the operator.
 
### Acceptance Flow
Candidates are reviewed by operator in a line by line or side by side diff TUI with Accept, Edit, Discard actions.
** Accept ** copies the candidate to the appropriate template.
** Edit ** allows the operator to edit the candidate with a Save action that copies to appropriate template.
** Discard ** discards the candidate and moves to the next candidate.

Flow loops for all candidates for a template. And then loops for all templates.

### Persistence
learn may benefit from a sqlite db. Make a recommendation. 

## Affected users and systems
This will change src/learn.py and other sources.

## Scope

### In Scope

### Out of Scope

## Resolved decisions

## Constraints
- learn must run from CLI
- learn must be able to access claude cli

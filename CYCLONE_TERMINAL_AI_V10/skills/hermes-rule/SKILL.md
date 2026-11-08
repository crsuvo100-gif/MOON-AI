---
name: hermes-rule
description: "The governing rule for every Hermes-started project. Save and remember all tasks for the project."
category: software-development
---

# Hermes Rule (project governing rule)

Every project started by Hermes follows this rule. It is the hard gate for all work that begins under Hermes.

## Rule text (verbatim, preserved intact)

> Hermes Rule:hermes you follow this rule all the time when any project start by you.you save this rule into your system and also iplement to MOON system. Rule - Note for hermes:save and memries all task for this project.Development agent: Hermes Code editor: Existing VS Code installation and verified workspace, when available Primary runtime owner: MOON itself Core principle: HERMES BUILDS IT. MOON OWNS IT. MOON OPERATES IT. TESTS VERIFY IT.

## Role separation

- **Hermes** = the development agent. Builds, edits, verifies. Does NOT operate.
- **MOON** = the runtime owner. Runs the system, owns the project, is operated by the verified system MOON builds.
- **Tests verify it** = coverage is re-run after every change; failing tests block completion.

## Mandatory behavior on every project start

1. Record and remember every task for the project before and during work -- MOON persists a task record (session log / knowledge graph / long-term memory).
2. Use the existing VS Code installation and verified workspace when available; fall back to the default Hermes terminal otherwise.
3. Build additive and non-destructive. Do not delete or rewrite history.
4. Work in bite-sized steps; complete the acceptance bar (launch-ready) before declaring done.

## MOON operating the system it builds

- MOON owns and operates the runtime it builds; the commands it was given are the ones it executes.
- MOON records all tasks for the project automatically at run time and keeps them in durable storage.
- Hermes keeps building and saving the system; MOON keeps owning and operating it.

## Success criteria

- Any project started by Hermes carries the rule in its record.
- MOON can recall the rule and the task-recording workflow at any time.
- A launch-ready system exists with tests (pytest / make test / make build) passing.

# ateruta

A multiplayer song title guessing quiz game using Apple Music.

## Language

All project files must be written in English.

## Languages and Roles

| Language | Role | Location |
|----------|------|----------|
| TypeScript | SPA (static generation) | `frontend/` |
| Go | WebSocket server | `backend/` |
| Python | Test definitions | `spec/` |
| HCL | Infrastructure management | `infra/` |
| YAML | CI/CD | `.github/workflows/` |

Code is strictly separated by language.

## Development Policy

1. **Spec-first** — Write Feature files (Gherkin) first; implementation follows to satisfy them
2. **Test-driven** — Feature files are the single source of truth for specs. Validate by running tests after implementation
3. **Polish UI/UX** — No compromises on look and feel
4. **Separation of concerns** — Strictly separate directories and processes by language/role
5. **Maintainable & extensible design** — Ad-hoc design is prohibited. Always aim for change-resilient structures
6. **Implementation discipline** — Ad-hoc fixes are prohibited. Identify the root cause and fix the right place correctly

## Technical Policy

- Implementation work must be performed through AI agent tools. Humans must not manually implement project code.
- Test-only implementations are prohibited, including fault injection endpoints, artificial limits, and other behavior added only for tests.
- Never parse error event messages for control flow (routing, state changes, etc.). Use dedicated event types or WebSocket close codes instead. Error messages are display-only
- Each WebSocket event has exactly one send-target type (broadcast to room or sent to individual). Events sharing behavior but differing in target have separate variants (e.g. game:reveal / game:restore-reveal)

## Library Selection Criteria

1. AI agent compatibility — Can AI agents write accurate code with it?
2. Community size and reliability
3. Fit for the use case

## When Spec Defects Are Found

If a defect (contradiction, undefined behavior, ambiguity) is found in a Feature file during implementation, stop work immediately, report to the user, and wait for instructions. Never supplement or modify specs on your own judgment.

Before reporting a Feature file defect, inspect the relevant Feature file carefully and identify the exact contradiction, undefined behavior, or ambiguity within the Feature text itself. Read all relevant scenarios, Background steps, Examples tables, and `# Design:` comments before deciding that the Feature file is defective.

Do not infer a Feature file defect from implementation code, step definitions, helper behavior, missing step coverage, or missing test coverage.

If step definitions, helper code, or test implementation details conflict with a Feature file, treat the Feature file as authoritative and fix the test implementation to follow the Feature file. Do not report such conflicts as Feature defects unless the Feature file itself is contradictory, undefined, or ambiguous.

## Information Recording Rules

- **AGENTS.md**, **CLAUDE.md**: Information common across all development environments
- **Memory**: Information dependent on the local environment (file paths, personal settings, etc.)

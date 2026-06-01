# features

Gherkin feature files — the single source of truth for specs.

## Structure

```
features/
├── backend/
├── frontend/
└── integration/
```

## Feature File Writing Rules

- **Scenarios**: Testable behavior only. Every scenario must be verifiable against a running system.
- **`# Design:` comments**: Rationale behind non-obvious design decisions.
- **AGENTS.md**, **CLAUDE.md**: Meta-rules about how to write and interpret feature files.

### Notation

- Broadcast: Use `broadcast to the room`. Do not use `broadcast to all players`.
- Error: Use `the player receives an error event with "..."`.
- C→S event: Use `{event} is sent to the server`. For debounced events, append `after a short delay`.
- Navigation: Use `the player is navigated to {destination}`.
- Event steps: One event per step for sequences. Alternative cases ("A or B") with identical behavior may share one step.
- Ordering: The order of steps and table rows defines the execution order. Do not add explicit order columns to tables.

### Error display (frontend only)

| Display method | Notation | Usage |
|---|---|---|
| Toast | `a toast "..." is displayed` or `the error message is displayed as a toast` | Server error events, client-side errors with no tied UI element. Auto-dismissing |
| Inline | `"..." is displayed` | Browser-side validation errors, unrecoverable connection errors. Tied to a specific UI element, cleared by a condition |
| Modal | `a modal displays "..."` | Overlay |

**Validation rule:** Backend feature files are the single source of truth for validation rules and error messages. Frontend specs reference backend specs via comments (e.g., `# Validations mirror room_settings.feature field validations`) instead of duplicating specific rules.

### Scenario structure

Success:

```gherkin
Scenario: ...
  Given [preconditions (phase, player state)]
  When [action]
  Then [state change]
  And [broadcast (always explicit, never omitted)]
```

Error:

```gherkin
Scenario: ...
  Given [preconditions]
  When [action]
  Then the player receives an error event with "..."
```

### Failure placement (Given vs Then)

A failure (server response, error event, fault) goes in Then when it occurs as a result of the When action in the scenario's causal chain. It goes in Given only when it describes a precondition state independent of the action.

Mock injection timing does not change placement: a response received after the action is Then, even if the test mocks it ahead of time.

### Step granularity

Make steps explicit only when they are central to the scenario's intent. Use abstract steps for incidental behavior; step definitions provide valid defaults.

- **Central**: changing this step's value or sequence alters the scenario's outcome or what is being verified
- **Incidental**: must occur for the scenario to run, but its specifics do not matter

### Content policy

Feature specs describe behavior only. Do not include:

- Library names/versions (e.g., Fuse.js, threshold 0.4)
- API calls/method names (e.g., mk.play(), mk.seekToTime(0))
- Regex patterns
- Internal state names/data structure paths (e.g., relationships.catalog.data[0])
- Source file references (e.g., useSocket.ts)
- Server internal state management (e.g., "the server marks the song as played"). Describe observable checks and outcomes, not how the server tracks them internally
- Visual appearance (colors, fonts, sizes, spacing, layout, styling) — e.g., "a **red** panel", "displayed **in gray**"

**Exception**: Technical details related to APIs (event names, HTTP endpoints, status codes) are allowed in backend and frontend specs. As a special case, `api.feature` may declare API type definitions using Then-only scenarios.

### Robustness

- An expression is fragile if a change elsewhere in the spec would make it incorrect or incomplete. Write expressions that remain valid as the spec evolves.
  - e.g., use `roomState is not null` instead of `playing or finished phase` — the latter breaks if a phase is added

### Design intent comments

Use `# Design:` comments to document the rationale behind non-obvious design decisions. These explain **why** a spec exists, not what it does.

Use cases:
- A decision that could reasonably have gone another way (e.g., why host status is never transferred)
- A value with no special significance that can be freely changed (e.g., a timeout duration)
- A restriction that has no strong rationale and could be removed

## API Naming Conventions

### Field names

| Category | Rule | Examples |
|---|---|---|
| Settings (game rules) | [topic] + [descriptor] | `playbackDurations`, `rankPoints`, `lockoutDuration`, `attemptsLimit` |
| Time point (ISO 8601 with TZ) | `~At` suffix | `expiresAt`, `lockoutExpiresAt` |
| Duration (seconds) | Annotate unit in type, not in name | `handicap: number (seconds)`, `lockoutDuration: number (seconds)` |
| Index | `~Index` suffix | `songIndex`, `rankIndex`, `playbackDurationIndex` |
| ID (standalone field) | `~Id` suffix | `playerId`, `songId`, `hostPlayerId` |
| ID (inside object) | `id` | `activePlayers[].id` |

### Scenario names and error messages

- Scenario names must use natural language, not camelCase field names
  - NG: `Scenario: Negative lockoutDuration is rejected`
  - OK: `Scenario: Negative lockout duration is rejected`
- Error messages use the human-readable form of field names
  - NG: `"rankPoints are required"`
  - OK: `"Rank points are required"`

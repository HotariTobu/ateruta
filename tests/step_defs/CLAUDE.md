# step_defs

pytest-bdd step definitions. Feature files live in `../features/{scope}/`.

## Structure

```
step_defs/
├── conftest.py                  # Shared fixtures
├── backend/                     # WebSocket server standalone
│   └── conftest.py              # WebSocket client connection fixtures
├── frontend/                    # SPA standalone (mock WebSocket)
│   └── conftest.py              # Playwright + mock WS server fixtures
└── integration/                 # Frontend + backend combined
    └── conftest.py              # Server + SPA connection fixtures
```

## Execution Context

All tests are E2E tests that run against externally running servers. Real-time waits (`time.sleep`, `wait_for_timeout`) are the correct approach for time-dependent behavior — test-only time manipulation is prohibited.

## Python Naming Conventions

- **No abbreviation** — use full words (`host`, not `h`). Comprehension iterators are exempt
- **No ambiguity** — qualify with context when the bare word is generic (`room_code`, not `code`)
- **No redundant suffixes** — omit type information derivable from context (`host_id`, not `host_player_id`)
- **Cross-layer consistency** — the same concept uses the same name in all context classes and test layers
- **`_` prefix** — file-private helpers only. Shared helpers in `helpers.py` have no prefix
- **Fixture pattern** — `make_{thing}` for factories, `{thing}` for single instances. Do not wrap simple function calls in fixtures

## Step Definition Rules

Every step definition must perform an action or verify a condition. `pass` is never acceptable:

- **Given**: Establish the precondition, or verify it was established by a preceding step
- **When**: Perform the action, or verify the action occurred
- **Then**: Assert the expected outcome

If a step cannot do any of these, the step should not exist in the Feature file. "Server internal state" is not an excuse — verify the observable consequences of that state.

Test-only implementations (fault injection endpoints, artificial limits, etc.) are prohibited. `pytest.skip` is acceptable only when a step can only be verified through a test-only mechanism. The skip reason must state why the step cannot be tested, not what mechanism would be needed.

## Comment Rules (Step Definitions)

Write comments only when the information cannot be derived from the code or the Feature file.

**Write:**

- **Event consumption tracking** — When a preceding step consumed a WS event via `expect_event`, explain why this step uses `ctx` or `find_last_event` instead
- **Step reuse cross-reference** — When a Feature step is defined in another file, note where (e.g., `# "the error message is displayed as a toast" is in conftest`)
- **Test strategy not derivable from Feature** — Mathematical reasoning, causal chains inside Given setups, or multi-step manipulation logic that the Feature scenario structure and the code alone do not explain

**Do not write:**

- Code paraphrasing (the next line is self-explanatory)
- Preconditions derivable from the Feature scenario structure
- Section dividers or decorative separators
- Explanations of unapproved design decisions

## Element Selection (Frontend Tests)

Use Playwright's role-based locators (`get_by_role`, `get_by_label`, `get_by_text`) to select elements. Do not use CSS selectors that guess implementation details (placeholder text, `input[type]`, etc.).

## Test Independence

Tests run in parallel and in random order. Every test must be independent:

- No shared mutable state between tests
- No dependency on execution order
- Each test sets up its own preconditions via fixtures

## Commands

@Makefile

Tests do not start or manage servers. Start them externally before running tests.

# spec

## Structure

```
spec/
├── features/                    # Gherkin specs
└── step_defs/                   # Step definitions
```

## Test Levels

- **backend/**: Connect directly to the server via WebSocket. No browser required. Includes HTTP API tests
- **frontend/**: Browser automation with Playwright. A mock WebSocket server is set up to validate the SPA
- **integration/**: Full E2E with Playwright against the server and SPA

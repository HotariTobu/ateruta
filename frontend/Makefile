.PHONY: dev build autofix inspection typecheck preflight

dev:
	bunx vite dev

build:
	bunx vite build

autofix:
	bunx --bun biome check --write

inspection:
	bunx --bun biome check

typecheck:
	bunx --bun tsc --build --noEmit

preflight: inspection typecheck

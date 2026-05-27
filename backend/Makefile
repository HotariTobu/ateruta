.PHONY: dev build autofix inspection typecheck preflight

dev:
	go tool air

build:
	go build -o ./bin/server ./cmd/server

autofix:
	golangci-lint run --fix ./...

inspection:
	golangci-lint run ./...
	govulncheck ./...

typecheck:
	go test ./...

preflight: inspection typecheck

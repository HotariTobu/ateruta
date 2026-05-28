package main

import (
	"bufio"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	appserver "ateruta/internal/server"
)

func main() {
	loadDotEnv("../.env")
	loadDotEnv(".env")

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	server := &http.Server{
		Addr:              ":" + port,
		Handler:           appserver.NewHandler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	log.Printf("ateruta backend listening on :%s", port)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func loadDotEnv(path string) {
	file, err := os.Open(path)
	if err != nil {
		return
	}
	defer func() {
		if err := file.Close(); err != nil {
			log.Printf("failed to close %s: %v", path, err)
		}
	}()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		if key == "" || os.Getenv(key) != "" {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), `"`)
		_ = os.Setenv(key, value)
	}
	if err := scanner.Err(); err != nil {
		log.Printf("failed to read %s: %v", path, err)
	}
}

import { env } from "node:process"
import { fileURLToPath } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import solid from "vite-plugin-solid"

const DEFAULT_PORT = 5050

function resolvePort(value: string | undefined): number {
  if (value === undefined) {
    return DEFAULT_PORT
  }

  const port = Number(value)
  return Number.isInteger(port) ? port : DEFAULT_PORT
}

export default defineConfig({
  plugins: [solid(), tailwindcss()],
  server: {
    port: resolvePort(env.PORT),
  },
  resolve: {
    alias: {
      "~": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
})

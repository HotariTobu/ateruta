const backendUrl = (): string => {
  return normalizeBackendUrl(import.meta.env.VITE_BACKEND_URL)
}

const normalizeBackendUrl = (value: unknown): string => {
  if (typeof value !== "string" || value.trim() === "") {
    return window.location.origin
  }
  return new URL(value, window.location.origin).origin
}

const backendApiUrl = (path: string): string =>
  new URL(path, `${backendUrl()}/`).toString()

function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(backendApiUrl(path), { ...init, credentials: "include" })
}

function backendWebSocketUrl(): string {
  const url = new URL(backendUrl())
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  url.pathname = "/ws"
  return url.toString()
}

export { backendFetch, backendWebSocketUrl }

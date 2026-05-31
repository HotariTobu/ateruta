import { render } from "solid-js/web"
import App from "./app"
import "./styles.css"

const root = document.getElementById("app")

if (root !== null) {
  render(() => <App />, root)
}

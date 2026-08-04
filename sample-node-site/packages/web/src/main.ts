// Static HUD frontend. Served same-origin via Caddy in prod; the ws base URL is
// env-driven so dev talks to :8080 while prod uses wss:// through the proxy.
const wsBase: string =
  import.meta.env.VITE_WS_URL ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;

const feed = document.getElementById("feed")!;

function connect(attempt = 0): void {
  const socket = new WebSocket(`${wsBase}/ws/levels`);
  socket.onmessage = (ev) => {
    feed.textContent = ev.data; // snapshot first, then deltas
  };
  socket.onclose = () => {
    // client auto-reconnect with backoff; server resends a snapshot on connect
    setTimeout(() => connect(attempt + 1), Math.min(1000 * 2 ** attempt, 30_000));
  };
}

connect();

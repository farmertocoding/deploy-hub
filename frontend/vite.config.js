import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const PAGE_CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${PAGE_CSP}" />`;

export default defineConfig({
  plugins: [react(), {
    name: "hub-csp",
    transformIndexHtml(html, ctx) {
      // Vite HMR cannot boot under script-src 'self'. Ship CSP on production
      // builds and `vite preview` only.
      if (ctx.server) return html;
      if (html.includes("Content-Security-Policy")) return html;
      return html.replace("<head>", `<head>\n    ${CSP_META}`);
    },
    configurePreviewServer(server) {
      server.middlewares.use((_req, res, next) => {
        res.setHeader("Content-Security-Policy", PAGE_CSP);
        next();
      });
    },
  }],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});

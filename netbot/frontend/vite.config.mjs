import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    {
      name: "development-csp",
      transformIndexHtml(html) {
        if (command !== "serve") return html;
        // Refresh needs Vite's inline preamble and a WebSocket only in development.
        return html
          .replace("script-src 'self';", "script-src 'self' 'unsafe-inline';")
          .replace(
            "connect-src 'self';",
            "connect-src 'self' ws://localhost:5173 ws://127.0.0.1:5173;",
          );
      },
    },
  ],
  server: {
    proxy: Object.fromEntries(
      ["/api", "/auth", "/admin", "/health"].map((path) => [
        path,
        {
          target: process.env.NETBOT_DEV_API_TARGET || "http://127.0.0.1:8000",
          changeOrigin: false,
        },
      ]),
    ),
  },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
    setupFiles: ["src/__tests__/setup.js"],
    restoreMocks: true,
  },
}));

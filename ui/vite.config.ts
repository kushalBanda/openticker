/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// openticker-serve serves the build (ADR 30); `pnpm dev` proxies to it, run as
// `openticker-serve --dev` so it accepts this dev server's origin.
const server = process.env.OPENTICKER_URL ?? "http://127.0.0.1:8750";
const proxied = { target: server, changeOrigin: true };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/openticker/adapters/inbound/web/dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 700, // the budget is 350 KB gzip for the first load (slice 13 checks it)
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api/v1/stream": { ...proxied, ws: true },
      "/api": proxied,
      "/login": proxied,
      "/brokers": proxied,
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/unit/setup.ts"],
    env: { NODE_ENV: "test" }, // React's test helpers exist only outside production
  },
});

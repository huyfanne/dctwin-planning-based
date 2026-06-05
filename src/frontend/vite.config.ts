import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,            // bind 0.0.0.0 so the dev UI is reachable over the network
    allowedHosts: true,    // accept any Host header (dev box reached via its LAN/cluster IP)
    proxy: { "/api": process.env.VITE_API_TARGET || "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});

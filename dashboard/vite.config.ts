/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev against a running stack: the gateway serves the API on 8443.
    proxy: { "/api": { target: "https://localhost:8443", secure: false } },
    // The Overview widget catalogue lives in shared/ (one file for project-service and the dashboard)
    fs: { allow: [".", "../shared/qeos_shared/overview_widgets.json"] },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // Typing-heavy UI tests run in parallel workers; 5 s was too tight on a loaded machine
    testTimeout: 15000,
    globals: true,
  },
});

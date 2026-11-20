import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const contracts = fileURLToPath(new URL("../contracts", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@contracts": contracts } },
  server: {
    // Fixtures live outside the frontend folder (repo-level contracts/).
    fs: { allow: [".."] },
    // Live mode in local development: forward API calls to the backend.
    proxy: { "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true } },
  },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});

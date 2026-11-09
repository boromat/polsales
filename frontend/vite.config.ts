/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const dir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(dir, "src") },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // Panel liczy dni w czasie polskim (decyzja #17). Bez wymuszenia strefy testy dat
    // przechodziłyby na maszynie w UTC (CI) także wtedy, gdy kod używa UTC zamiast lokalnej.
    env: { TZ: "Europe/Warsaw" },
  },
  build: {
    rollupOptions: {
      output: {
        // Code-splitting: recharts (ciężki) w osobnym chunku, reszta vendorów osobno.
        // Funkcja zamiast obiektu: Vite 8 (Rolldown) nie przyjmuje obiektowej postaci manualChunks.
        manualChunks(id: string) {
          if (/node_modules\/(recharts|d3-|victory-vendor|internmap)/.test(id)) return "recharts";
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|@tanstack)\//.test(id)) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    // Proxy API na backend w trybie dev.
    proxy: {
      // xfwd: proxy dokłada X-Forwarded-Host, po którym backend rozpoznaje żądania z tej samej
      // strony (ochrona CSRF porównuje Origin z Host / X-Forwarded-Host).
      "/api": { target: "http://localhost:8000", xfwd: true },
    },
  },
});

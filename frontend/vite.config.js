import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },

  // ── Monaco Web Worker fix ──────────────────────────────────────────────────
  // Without this, Vite can't resolve Monaco's worker entry points and falls
  // back to fetching them from CDN — which gets blocked by CSP, crashing the
  // React tree with a blank page.
  optimizeDeps: {
    include: ["monaco-editor/esm/vs/editor/editor.worker"],
    exclude: ["@monaco-editor/react"],
  },

  worker: {
    format: "es",
  },

  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react":  ["react", "react-dom", "react-router-dom"],
          "vendor-charts": ["recharts"],
          "vendor-table":  ["@tanstack/react-table", "@tanstack/react-query"],
          "vendor-editor": ["monaco-editor"],
          "vendor-ui":     ["lucide-react", "sonner", "zustand"],
        },
      },
    },
  },
});
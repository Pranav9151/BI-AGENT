var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
var devProxyTarget = (_a = process.env.VITE_DEV_PROXY_TARGET) !== null && _a !== void 0 ? _a : "http://localhost:8000";
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
        },
    },
    // ── Monaco Web Worker fix ──────────────────────────────────────────────────
    // Monaco spins up Web Workers for language services (JSON, TypeScript, CSS).
    // Without this, Vite can't resolve the worker entry points, so Monaco silently
    // falls back to the CDN — which then gets blocked by CSP or CORS, crashing
    // the entire React tree with a blank page.
    //
    // This tells Vite to treat monaco-editor worker files as assets and serve them
    // from the local bundle, bypassing the CDN entirely.
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
                target: devProxyTarget,
                changeOrigin: true,
            },
            "/health": {
                target: devProxyTarget,
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
                    "vendor-react": ["react", "react-dom", "react-router-dom"],
                    "vendor-charts": ["recharts"],
                    "vendor-table": ["@tanstack/react-table", "@tanstack/react-query"],
                    "vendor-editor": ["monaco-editor"],
                    "vendor-ui": ["lucide-react", "sonner", "zustand"],
                },
            },
        },
    },
});

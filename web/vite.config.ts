import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // The source is mounted from the Mac, and file events miss editors that save by replacing
    // the file, so hot reload has to poll.
    watch: { usePolling: true, interval: 200 },
    // The browser calls /api on its own origin, so the API needs no CORS rules.
    proxy: {
      "/api": {
        target: "http://api:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

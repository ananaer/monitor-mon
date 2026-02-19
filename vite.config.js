import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  root: ".",
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        admin: resolve(__dirname, "admin.html"),
        alerts: resolve(__dirname, "alerts.html"),
        policies: resolve(__dirname, "policies.html"),
      },
    },
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import autoprefixer from "autoprefixer";
import tailwindcss from "tailwindcss";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const sourceRoot = fileURLToPath(new URL("./src", import.meta.url));
const staticOutput = fileURLToPath(new URL("../backend/app/static/react", import.meta.url));
const tailwindConfig = fileURLToPath(new URL("./tailwind.config.ts", import.meta.url));

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  base: "/static/react/",
  css: {
    postcss: {
      plugins: [tailwindcss({ config: tailwindConfig }), autoprefixer()]
    }
  },
  resolve: {
    alias: {
      "@": sourceRoot
    }
  },
  build: {
    outDir: staticOutput,
    emptyOutDir: true
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/logout": "http://localhost:8000"
    }
  }
});

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import { runtimeLicenseNotices } from "./scripts/runtime-license-notices.mjs";

export default defineConfig({
  root: fileURLToPath(new URL("./static", import.meta.url)),
  publicDir: false,
  plugins: [react(), runtimeLicenseNotices()],
  build: {
    emptyOutDir: true,
    outDir: fileURLToPath(new URL("./static-dist", import.meta.url)),
    sourcemap: false,
  },
});

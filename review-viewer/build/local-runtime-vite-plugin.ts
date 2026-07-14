import { access, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import type { Plugin } from "vite";

const SECURITY_HEADERS = {
  "Content-Security-Policy": "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
  "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
} as const;

function localWorkerSource(): string {
  return [
    'import handler from "./ssr/index.js";',
    `const SECURITY_HEADERS = ${JSON.stringify(SECURITY_HEADERS)};`,
    "function secured(response) {",
    "  const result = new Response(response.body, response);",
    "  for (const [name, value] of Object.entries(SECURITY_HEADERS)) result.headers.set(name, value);",
    "  return result;",
    "}",
    "export default {",
    "  async fetch(request) { return secured(await handler.fetch(request)); },",
    "};",
    "",
  ].join("\n");
}

/**
 * Preserve local preview and test support on Node 22.14. Cloudflare's current
 * adapter requires module.registerHooks, which landed later in Node 22. The
 * fallback is deliberately local-only; capable runtimes still build the full
 * Cloudflare worker through the official adapter.
 */
export function localRuntimeCompatibility(cloudflareAdapterAvailable: boolean): Plugin {
  let root = process.cwd();

  return {
    name: "local-runtime-compatibility",
    configResolved(config) {
      root = config.root;
    },
    configureServer(server) {
      server.middlewares.use((_request, response, next) => {
        for (const [name, value] of Object.entries(SECURITY_HEADERS)) response.setHeader(name, value);
        next();
      });
    },
    async closeBundle() {
      if (cloudflareAdapterAvailable) return;
      const ssrEntry = resolve(root, "dist/server/ssr/index.js");
      try {
        await access(ssrEntry);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
        throw error;
      }
      const fallbackEntry = resolve(root, "dist/server/local-worker.js");
      await mkdir(dirname(fallbackEntry), { recursive: true });
      await writeFile(fallbackEntry, localWorkerSource());
    },
  };
}

// Copies Playwright's trace viewer (playwright-core, version pinned exactly in package.json) to dist/trace-viewer/,
// which the dashboard's nginx serves from the same origin (ADR-037). Run after `vite build`, which empties dist/.
// A missing viewer stops the build: an image without it would answer "Trace" with a 404.
import { cpSync, existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
let core;
try {
  core = dirname(require.resolve("playwright-core/package.json"));
} catch {
  console.error("copy-trace-viewer: playwright-core is not installed (npm ci)");
  process.exit(1);
}
const source = join(core, "lib", "vite", "traceViewer");
if (!existsSync(join(source, "index.html"))) {
  console.error(`copy-trace-viewer: ${source} has no index.html; did playwright-core move its trace viewer?`);
  process.exit(1);
}
const target = fileURLToPath(new URL("../dist/trace-viewer/", import.meta.url));
cpSync(source, target, { recursive: true });
const { version } = JSON.parse(readFileSync(join(core, "package.json"), "utf8"));
console.log(`copy-trace-viewer: playwright-core ${version} trace viewer -> dist/trace-viewer/`);

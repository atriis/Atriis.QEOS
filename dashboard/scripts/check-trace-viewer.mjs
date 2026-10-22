// Fails the build when dist/ lacks the self-hosted trace viewer (ADR-037): its page, the service worker that reads
// the trace, and the snapshot page. Run after copy-trace-viewer.mjs.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const viewer = fileURLToPath(new URL("../dist/trace-viewer/", import.meta.url));
const missing = ["index.html", "sw.bundle.js", "snapshot.html"].filter((f) => !existsSync(viewer + f));
if (missing.length) {
  console.error(`check-trace-viewer: dist/trace-viewer/ lacks ${missing.join(", ")}`);
  process.exit(1);
}
console.log("check-trace-viewer: dist/trace-viewer/ is complete");

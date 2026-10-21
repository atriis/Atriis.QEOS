// Cucumber hook that records a Playwright trace and tells QEOS where it is (ADR-037).
// Needs QEOS with ADR-037, collector 0.14.0 and the project switch "Keep traces from uploads".
// Until an owner turns the switch on, the collector sends nothing.
const { Before, After } = require("@cucumber/cucumber");
const path = require("path");

Before(async function () {
  await this.context.tracing.start({ screenshots: true, snapshots: true });
});

After(async function (scenario) {
  const tracePath = path.join("test-results", "traces", `${scenario.pickle.id}.zip`);
  await this.context.tracing.stop({ path: tracePath });
  this.attach(JSON.stringify({ kind: "trace", path: tracePath }), "application/vnd.qeos.artifact+json");
});

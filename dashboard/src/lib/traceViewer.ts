/**
 * Can this browser run the self-hosted trace viewer (ADR-037)? The viewer reads the trace through a service worker,
 * and a browser registers one only from an origin whose certificate it trusts: after clicking through the warning
 * of a self-signed certificate the page loads but the viewer stays blank. Registering the viewer's own worker, with
 * the viewer's scope, answers the question; it is the same registration the viewer makes when it opens.
 */
const SCRIPT = "/trace-viewer/sw.bundle.js";
const SCOPE = "/trace-viewer/";

let ready: Promise<boolean> | undefined;

export function canRunTraceViewer(): Promise<boolean> {
  const workers = navigator.serviceWorker as ServiceWorkerContainer | undefined;
  if (!workers) return Promise.resolve(false);
  // A success holds for the page; a failure is checked again next time (the certificate may be trusted by then)
  ready ??= workers.register(SCRIPT, { scope: SCOPE }).then(
    () => true,
    () => { ready = undefined; return false; },
  );
  return ready;
}

/** For tests: forget the answer. */
export function resetTraceViewerCheck(): void {
  ready = undefined;
}

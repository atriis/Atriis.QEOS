/** Leaves the single-page app for a page the server answers (Grafana under /grafana/). Its own module so
 *  tests can mock it: jsdom cannot navigate. Callers pass a same-origin relative path, never a URL built
 *  from input. */
export function goTo(url: string): void {
  window.location.assign(url);
}

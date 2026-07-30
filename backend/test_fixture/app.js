// Endpoint referenced here but never actually called by any click handler —
// this is what JS scanning should discover that live crawling alone misses.
const HIDDEN_ENDPOINT = "/api/hidden/stats";

function neverCalled() {
  return fetch(HIDDEN_ENDPOINT).then((r) => r.json());
}

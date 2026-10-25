// Requests go to this page's own origin — Vite's dev server proxies /api
// (see vite.config.ts) to the backend, which stays bound to 127.0.0.1 and is
// never exposed directly, even when the frontend is reachable externally.
const API_BASE = "";

function wsBase(): string {
  return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
}

export async function startCrawl(
  startUrl: string,
  proxyServer?: string,
  saveSession: boolean = false
): Promise<{ session_id: string; novnc_url: string }> {
  const res = await fetch(`${API_BASE}/api/crawl/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_url: startUrl, proxy_server: proxyServer || null, save_session: saveSession }),
  });
  if (!res.ok) throw new Error(`start crawl failed: ${res.status}`);
  return res.json();
}

export async function stopCrawl(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/stop`, { method: "POST" });
}

export interface SavedSession {
  session_id: string;
  label: string;
  start_url: string;
  created_at: string;
  updated_at: string;
  endpoint_count: number;
  active: boolean;
}

export async function listSavedSessions(): Promise<SavedSession[]> {
  const res = await fetch(`${API_BASE}/api/crawl/sessions`);
  if (!res.ok) throw new Error(`failed to list saved sessions: ${res.status}`);
  const data = await res.json();
  return data.sessions ?? [];
}

export async function resumeSession(
  sessionId: string
): Promise<{ session_id: string; novnc_url: string; captured_count: number }> {
  const res = await fetch(`${API_BASE}/api/crawl/sessions/${sessionId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `resume failed: ${res.status}`);
  }
  return res.json();
}

export async function deleteSavedSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/crawl/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `delete failed: ${res.status}`);
  }
}

export interface DiscoveredEndpoint {
  method: string;
  path_template: string;
  host: string;
  scheme: string;
  query_params: string[];
  path_params: string[];
  status_codes_seen: number[];
  hit_count: number;
  discovery_source: "observed" | "js_scan_verified";
}

export async function getEndpoints(sessionId: string): Promise<DiscoveredEndpoint[]> {
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/endpoints`);
  const data = await res.json();
  return data.endpoints ?? [];
}

export async function getProxyCaCertStatus(): Promise<{ configured: boolean }> {
  const res = await fetch(`${API_BASE}/api/settings/proxy-ca-cert`);
  if (!res.ok) throw new Error(`failed to load proxy CA cert status: ${res.status}`);
  return res.json();
}

export async function uploadProxyCaCert(file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/settings/proxy-ca-cert`, { method: "PUT", body: formData });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `upload failed: ${res.status}`);
  }
}

export async function deleteProxyCaCert(): Promise<void> {
  await fetch(`${API_BASE}/api/settings/proxy-ca-cert`, { method: "DELETE" });
}

export async function checkProxyReachable(
  host: string,
  port: number
): Promise<{ reachable: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/crawl/proxy/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host, port }),
  });
  return res.json();
}

export async function uploadFile(
  sessionId: string,
  file: File
): Promise<{ status: string; filename: string; size: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `upload failed: ${res.status}`);
  }
  return res.json();
}

export async function scanJs(sessionId: string): Promise<{ found_count: number }> {
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/scan-js`, { method: "POST" });
  if (!res.ok) throw new Error(`JS scan failed: ${res.status}`);
  return res.json();
}

export interface Exclusions {
  hosts: string[];
  endpoints: { method: string; host: string; path_template: string }[];
  extensions: string[];
  methods: string[];
}

export async function getExclusions(sessionId: string): Promise<Exclusions> {
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/exclusions`);
  return res.json();
}

export async function getStaticExtensionGroups(): Promise<Record<string, string[]>> {
  const res = await fetch(`${API_BASE}/api/crawl/static-extension-groups`);
  return res.json();
}

export async function excludeExtension(sessionId: string, extension: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/exclude-extension`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extension }),
  });
}

export async function includeExtension(sessionId: string, extension: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/include-extension`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extension }),
  });
}

export async function excludeMethod(sessionId: string, method: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/exclude-method`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method }),
  });
}

export async function includeMethod(sessionId: string, method: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/include-method`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method }),
  });
}

export async function excludeHost(sessionId: string, host: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/exclude-host`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host }),
  });
}

export async function includeHost(sessionId: string, host: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/include-host`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host }),
  });
}

export async function excludeEndpoint(
  sessionId: string,
  method: string,
  host: string,
  pathTemplate: string
): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/exclude-endpoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method, host, path_template: pathTemplate }),
  });
}

export async function includeEndpoint(
  sessionId: string,
  method: string,
  host: string,
  pathTemplate: string
): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/include-endpoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method, host, path_template: pathTemplate }),
  });
}

export async function exportCrawl(
  sessionId: string,
  groupByHost: boolean = false
): Promise<{
  openapi: object;
  postman: object;
  endpoint_count: number;
}> {
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/export?group_by_host=${groupByHost}`);
  return res.json();
}

export function crawlStreamUrl(sessionId: string): string {
  return `${wsBase()}/api/crawl/${sessionId}/stream`;
}

export function downloadJson(data: object, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}


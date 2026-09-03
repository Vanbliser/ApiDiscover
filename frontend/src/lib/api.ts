// Derive the backend host from wherever this page was actually loaded from
// (localhost vs 127.0.0.1 vs a LAN IP are all distinct browser origins) —
// hardcoding "localhost" here broke access from any other loopback form.
// The backend port is injected at build/dev time via VITE_BACKEND_PORT so
// run.sh can point the frontend at a non-default backend port.
const BACKEND_PORT = import.meta.env.VITE_BACKEND_PORT || "8000";
const API_BASE = `${window.location.protocol}//${window.location.hostname}:${BACKEND_PORT}`;

export interface LiveHost {
  hostname: string;
  sources: string[];
  status_code: number | null;
  title: string | null;
  server_header: string | null;
  resolved_ips: string[];
  reachable: boolean;
}

export interface ProviderConfig {
  name: string;
  enabled: boolean;
  api_key: string | null;
  cookies: Record<string, string>;
  extra: Record<string, string>;
}

export function reconStreamUrl(): string {
  return `${API_BASE.replace("http", "ws")}/api/recon/stream`;
}

export async function listProviders(): Promise<ProviderConfig[]> {
  const res = await fetch(`${API_BASE}/api/recon/providers`);
  if (!res.ok) throw new Error(`failed to load provider settings: ${res.status}`);
  return res.json();
}

export async function upsertProvider(
  name: string,
  enabled: boolean,
  apiKey: string = "",
  cookies: Record<string, string> = {},
  extra: Record<string, string> = {}
): Promise<void> {
  await fetch(`${API_BASE}/api/recon/providers`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, enabled, api_key: apiKey, cookies, extra }),
  });
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
  const res = await fetch(`${API_BASE}/api/recon/proxy-ca-cert`);
  if (!res.ok) throw new Error(`failed to load proxy CA cert status: ${res.status}`);
  return res.json();
}

export async function uploadProxyCaCert(file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/recon/proxy-ca-cert`, { method: "PUT", body: formData });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `upload failed: ${res.status}`);
  }
}

export async function deleteProxyCaCert(): Promise<void> {
  await fetch(`${API_BASE}/api/recon/proxy-ca-cert`, { method: "DELETE" });
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
  return `${API_BASE.replace("http", "ws")}/api/crawl/${sessionId}/stream`;
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

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

export function downloadCsv(rows: (string | number | null)[][], filename: string): void {
  const csv = rows
    .map((row) => row.map((cell) => csvEscape(cell === null ? "" : String(cell))).join(","))
    .join("\r\n");
  // Leading BOM so Excel opens the file as UTF-8 instead of guessing wrong.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

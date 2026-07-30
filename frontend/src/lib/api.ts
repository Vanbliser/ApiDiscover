// Derive the backend host from wherever this page was actually loaded from
// (localhost vs 127.0.0.1 vs a LAN IP are all distinct browser origins) —
// hardcoding "localhost" here broke access from any other loopback form.
const API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

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
  startUrl: string
): Promise<{ session_id: string; novnc_url: string }> {
  const res = await fetch(`${API_BASE}/api/crawl/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_url: startUrl }),
  });
  if (!res.ok) throw new Error(`start crawl failed: ${res.status}`);
  return res.json();
}

export async function stopCrawl(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/stop`, { method: "POST" });
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

export async function scanJs(sessionId: string): Promise<{ found_count: number }> {
  const res = await fetch(`${API_BASE}/api/crawl/${sessionId}/scan-js`, { method: "POST" });
  if (!res.ok) throw new Error(`JS scan failed: ${res.status}`);
  return res.json();
}

export async function excludeHost(sessionId: string, host: string): Promise<void> {
  await fetch(`${API_BASE}/api/crawl/${sessionId}/exclude-host`, {
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

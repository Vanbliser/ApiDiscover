import { useEffect, useState } from "react";
import {
  type DiscoveredEndpoint,
  type Exclusions,
  getEndpoints,
  getExclusions,
  getStaticExtensionGroups,
  excludeHost,
  includeHost,
  excludeEndpoint,
  includeEndpoint,
  excludeExtension,
  includeExtension,
  excludeMethod,
  includeMethod,
  exportCrawl,
  downloadJson,
  scanJs,
} from "../lib/api";

interface Props {
  sessionId: string;
  refreshSignal: number;
  onClose: () => void;
}

export function CapturedEndpointsPanel({ sessionId, refreshSignal, onClose }: Props) {
  const [endpoints, setEndpoints] = useState<DiscoveredEndpoint[]>([]);
  const [exclusions, setExclusions] = useState<Exclusions>({ hosts: [], endpoints: [], extensions: [], methods: [] });
  const [extensionGroups, setExtensionGroups] = useState<Record<string, string[]>>({});
  const [groupByHost, setGroupByHost] = useState(false);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [lastScanFound, setLastScanFound] = useState<number | null>(null);
  const [methodInput, setMethodInput] = useState("");

  async function refresh() {
    setEndpoints(await getEndpoints(sessionId));
    setExclusions(await getExclusions(sessionId));
  }

  useEffect(() => {
    refresh();
  }, [sessionId, refreshSignal]);

  useEffect(() => {
    getStaticExtensionGroups().then(setExtensionGroups);
  }, []);

  const allStaticExtensions = Object.values(extensionGroups).flat();
  const allStaticExcluded =
    allStaticExtensions.length > 0 && allStaticExtensions.every((ext) => exclusions.extensions.includes(ext));

  async function handleToggleAllStatic() {
    if (allStaticExcluded) {
      await Promise.all(allStaticExtensions.map((ext) => includeExtension(sessionId, ext)));
    } else {
      await Promise.all(allStaticExtensions.map((ext) => excludeExtension(sessionId, ext)));
    }
    await refresh();
  }

  async function handleToggleExtension(ext: string) {
    if (exclusions.extensions.includes(ext)) {
      await includeExtension(sessionId, ext);
    } else {
      await excludeExtension(sessionId, ext);
    }
    await refresh();
  }

  async function handleExcludeMethodInput() {
    const method = methodInput.trim().toUpperCase();
    if (!method) return;
    await excludeMethod(sessionId, method);
    setMethodInput("");
    await refresh();
  }

  async function handleIncludeMethod(method: string) {
    await includeMethod(sessionId, method);
    await refresh();
  }

  async function handleExcludeEndpoint(ep: DiscoveredEndpoint) {
    await excludeEndpoint(sessionId, ep.method, ep.host, ep.path_template);
    await refresh();
  }

  async function handleIncludeEndpoint(ep: { method: string; host: string; path_template: string }) {
    await includeEndpoint(sessionId, ep.method, ep.host, ep.path_template);
    await refresh();
  }

  async function handleExcludeHost(host: string) {
    await excludeHost(sessionId, host);
    await refresh();
  }

  async function handleIncludeHost(host: string) {
    await includeHost(sessionId, host);
    await refresh();
  }

  async function handleScanJs() {
    setScanning(true);
    setScanError(null);
    setLastScanFound(null);
    try {
      const result = await scanJs(sessionId);
      setLastScanFound(result.found_count);
      await refresh();
    } catch (e) {
      setScanError(e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(false);
    }
  }

  async function handleExport() {
    setLoading(true);
    try {
      const result = await exportCrawl(sessionId, groupByHost);
      downloadJson(result.openapi, "discovered-api.openapi.json");
      downloadJson(result.postman, "discovered-api.postman_collection.json");
    } finally {
      setLoading(false);
    }
  }

  const hosts = Array.from(new Set(endpoints.map((e) => e.host))).sort();

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Captured APIs ({endpoints.length})</h2>
        <button onClick={onClose}>Back to browser</button>
      </div>

      <p className="hint">
        Exclude a specific request or an entire base URL to hide it from this list and the
        export — nothing is deleted, so an accidental exclusion can always be undone below.
        Exclusions apply for the rest of this crawl session.
      </p>

      <div className="row">
        <button onClick={handleScanJs} disabled={scanning}>
          {scanning ? "Scanning JS files..." : "Scan JS files for endpoints"}
        </button>
        {lastScanFound !== null && (
          <span className="hint">
            {lastScanFound > 0
              ? `Found and verified ${lastScanFound} additional endpoint(s) referenced in JS.`
              : "No additional live endpoints found in JS."}
          </span>
        )}
        {scanError && <span className="error">{scanError}</span>}
      </div>

      <div className="row" style={{ flexWrap: "wrap" }}>
        <button onClick={handleToggleAllStatic} disabled={allStaticExtensions.length === 0}>
          {allStaticExcluded ? "Re-include static files" : "Exclude static files (css/html/js/images/fonts)"}
        </button>
        {Object.entries(extensionGroups).map(([group, exts]) => {
          const allExcludedInGroup = exts.length > 0 && exts.every((ext) => exclusions.extensions.includes(ext));
          return (
            <button
              key={group}
              className={allExcludedInGroup ? "host-exclude-chip host-include-chip" : "host-exclude-chip"}
              onClick={() => exts.forEach((ext) => handleToggleExtension(ext))}
              title={exts.map((e) => `.${e}`).join(", ")}
            >
              {allExcludedInGroup ? `↩ ${group}` : `${group} ✕`}
            </button>
          );
        })}
      </div>

      <div className="row" style={{ flexWrap: "wrap" }}>
        <input
          placeholder="Exclude method (e.g. OPTIONS)"
          value={methodInput}
          onChange={(e) => setMethodInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleExcludeMethodInput()}
          style={{ width: 200 }}
        />
        <button onClick={handleExcludeMethodInput} disabled={!methodInput.trim()}>
          Exclude method
        </button>
        {exclusions.methods.map((method) => (
          <button key={method} className="host-exclude-chip host-include-chip" onClick={() => handleIncludeMethod(method)}>
            ↩ Re-include {method}
          </button>
        ))}
      </div>

      {hosts.length > 0 && (
        <div className="host-exclude-row">
          {hosts.map((host) => (
            <button key={host} className="host-exclude-chip" onClick={() => handleExcludeHost(host)}>
              Exclude all of {host} ✕
            </button>
          ))}
        </div>
      )}

      {exclusions.hosts.length > 0 && (
        <div className="host-exclude-row">
          <span className="hint">Excluded hosts:</span>
          {exclusions.hosts.map((host) => (
            <button key={host} className="host-exclude-chip host-include-chip" onClick={() => handleIncludeHost(host)}>
              ↩ Re-include {host}
            </button>
          ))}
        </div>
      )}

      {exclusions.endpoints.length > 0 && (
        <div className="host-exclude-row">
          <span className="hint">Excluded endpoints:</span>
          {exclusions.endpoints.map((ep) => (
            <button
              key={`${ep.method}-${ep.host}-${ep.path_template}`}
              className="host-exclude-chip host-include-chip"
              onClick={() => handleIncludeEndpoint(ep)}
            >
              ↩ Re-include {ep.method} {ep.host}{ep.path_template}
            </button>
          ))}
        </div>
      )}

      <table className="results-table">
        <thead>
          <tr>
            <th>Method</th>
            <th>Host</th>
            <th>Path</th>
            <th>Hits</th>
            <th>Status codes</th>
            <th>Source</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep) => (
            <tr key={`${ep.method}-${ep.host}-${ep.path_template}`}>
              <td>{ep.method}</td>
              <td>{ep.host}</td>
              <td>{ep.path_template}</td>
              <td>{ep.hit_count}</td>
              <td>{ep.status_codes_seen.join(", ")}</td>
              <td>
                {ep.discovery_source === "js_scan_verified" ? (
                  <span className="source-tag source-js-scan" title="Found as a string literal in JS source, confirmed with a live request — never organically triggered by clicking through the app">
                    found in JS
                  </span>
                ) : (
                  <span className="source-tag source-observed">observed</span>
                )}
              </td>
              <td>
                <button onClick={() => handleExcludeEndpoint(ep)}>Exclude</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row">
        <label className="provider-toggle">
          <input
            type="checkbox"
            checked={groupByHost}
            onChange={(e) => setGroupByHost(e.target.checked)}
          />
          Group Postman collection by host
        </label>
        <button onClick={handleExport} disabled={loading || endpoints.length === 0}>
          {loading ? "Exporting..." : "Export (OpenAPI + Postman)"}
        </button>
      </div>
    </div>
  );
}

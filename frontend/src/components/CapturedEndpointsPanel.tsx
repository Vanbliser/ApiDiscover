import { useEffect, useState } from "react";
import {
  type DiscoveredEndpoint,
  getEndpoints,
  excludeHost,
  excludeEndpoint,
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
  const [groupByHost, setGroupByHost] = useState(false);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [lastScanFound, setLastScanFound] = useState<number | null>(null);

  async function refresh() {
    setEndpoints(await getEndpoints(sessionId));
  }

  useEffect(() => {
    refresh();
  }, [sessionId, refreshSignal]);

  async function handleExcludeEndpoint(ep: DiscoveredEndpoint) {
    await excludeEndpoint(sessionId, ep.method, ep.host, ep.path_template);
    await refresh();
  }

  async function handleExcludeHost(host: string) {
    await excludeHost(sessionId, host);
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
        Deselect a request to remove it and stop capturing further calls that match it, or
        exclude an entire base URL. Exclusions apply for the rest of this crawl session.
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

      {hosts.length > 0 && (
        <div className="host-exclude-row">
          {hosts.map((host) => (
            <button key={host} className="host-exclude-chip" onClick={() => handleExcludeHost(host)}>
              Exclude all of {host} ✕
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

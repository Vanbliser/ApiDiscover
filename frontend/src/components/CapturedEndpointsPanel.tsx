import { useEffect, useState } from "react";
import {
  type DiscoveredEndpoint,
  getEndpoints,
  excludeHost,
  excludeEndpoint,
  exportCrawl,
  downloadJson,
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

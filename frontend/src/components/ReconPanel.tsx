import { useState } from "react";
import { runRecon, type LiveHost } from "../lib/api";

interface Props {
  onSelectTarget: (url: string) => void;
}

export function ReconPanel({ onSelectTarget }: Props) {
  const [domain, setDomain] = useState("");
  const [loading, setLoading] = useState(false);
  const [hosts, setHosts] = useState<LiveHost[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    if (!domain) return;
    setLoading(true);
    setError(null);
    try {
      const result = await runRecon(domain);
      setHosts(result.hosts);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h2>Domain Recon</h2>
      <div className="row">
        <input
          placeholder="example.com"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleRun()}
        />
        <button onClick={handleRun} disabled={loading}>
          {loading ? "Scanning..." : "Run recon"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {hosts.length > 0 && (
        <table className="results-table">
          <thead>
            <tr>
              <th>Hostname</th>
              <th>Sources</th>
              <th>Status</th>
              <th>Title</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {hosts.map((h) => (
              <tr key={h.hostname}>
                <td>{h.hostname}</td>
                <td>{h.sources.join(", ")}</td>
                <td>{h.reachable ? h.status_code : "unreachable"}</td>
                <td>{h.title ?? "—"}</td>
                <td>
                  {h.reachable && (
                    <button onClick={() => onSelectTarget(`https://${h.hostname}`)}>
                      Send to App Crawl
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

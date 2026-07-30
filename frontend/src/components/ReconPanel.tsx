import { useRef, useState } from "react";
import { downloadCsv, reconStreamUrl, type LiveHost } from "../lib/api";

interface Props {
  onSelectTarget: (url: string) => void;
}

function parseDomains(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\n,]/)
        .map((d) => d.trim())
        .filter(Boolean)
    )
  );
}

interface ProviderErrorInfo {
  provider: string;
  message: string;
}

export function ReconPanel({ onSelectTarget }: Props) {
  const [domainInput, setDomainInput] = useState("");
  const [running, setRunning] = useState(false);
  const [hosts, setHosts] = useState<LiveHost[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [providerErrors, setProviderErrors] = useState<ProviderErrorInfo[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const domains = parseDomains(domainInput);

  function handleRun() {
    if (running) return;
    setError(null);
    setProviderErrors([]);
    setHosts([]);
    setRunning(true);

    const ws = new WebSocket(reconStreamUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ domains }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "host") {
        const host: LiveHost = msg.data;
        setHosts((prev) => {
          const idx = prev.findIndex((h) => h.hostname === host.hostname);
          if (idx === -1) return [...prev, host];
          const next = [...prev];
          next[idx] = host;
          return next;
        });
      } else if (msg.type === "provider_error") {
        setProviderErrors((prev) => [...prev, { provider: msg.provider, message: msg.message }]);
      } else if (msg.type === "error") {
        setError(msg.message);
        setRunning(false);
      } else if (msg.type === "done") {
        setRunning(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setError("Connection to backend lost during recon run.");
      setRunning(false);
    };

    ws.onclose = () => {
      setRunning(false);
    };
  }

  function handleStop() {
    wsRef.current?.close();
    setRunning(false);
  }

  const sortedHosts = [...hosts].sort((a, b) => a.hostname.localeCompare(b.hostname));

  function handleExportCsv() {
    const header = ["Hostname", "Sources", "Status", "Title", "Server", "Resolved IPs", "Reachable"];
    const rows = sortedHosts.map((h) => [
      h.hostname,
      h.sources.join("; "),
      h.reachable ? h.status_code : "unreachable",
      h.title ?? "",
      h.server_header ?? "",
      h.resolved_ips.join("; "),
      h.reachable ? "yes" : "no",
    ]);
    downloadCsv([header, ...rows], `recon-results-${sortedHosts.length}-hosts.csv`);
  }

  return (
    <div className="panel">
      <h2>Domain Recon</h2>
      <p className="hint">
        Enter one or more domains (comma or newline separated). You can also leave this empty and
        run with only account-wide providers enabled in Settings (e.g. Wallarm, which lists your
        whole account's attack surface regardless of domain).
      </p>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <textarea
          className="domain-input"
          placeholder={"example.com\napi.example.com, another.com"}
          value={domainInput}
          onChange={(e) => setDomainInput(e.target.value)}
          disabled={running}
          rows={2}
        />
        {running ? (
          <button onClick={handleStop}>Stop ({hosts.length} found so far)</button>
        ) : (
          <button onClick={handleRun}>
            Run recon{domains.length > 0 ? ` (${domains.length} domain${domains.length > 1 ? "s" : ""})` : ""}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {providerErrors.map((pe, i) => (
        <p className="error" key={`${pe.provider}-${i}`}>
          {pe.provider}: {pe.message}
        </p>
      ))}
      {running && hosts.length === 0 && providerErrors.length === 0 && (
        <p className="hint">Scanning — results will appear as they're found...</p>
      )}
      {sortedHosts.length > 0 && (
        <>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <p className="hint" style={{ margin: 0 }}>
              {sortedHosts.length} host{sortedHosts.length > 1 ? "s" : ""} found
            </p>
            <button onClick={handleExportCsv}>Export CSV</button>
          </div>
          <div className="results-table-scroll">
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
                {sortedHosts.map((h) => (
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
          </div>
        </>
      )}
    </div>
  );
}

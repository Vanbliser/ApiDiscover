import { useRef, useState } from "react";
import { checkProxyReachable, startCrawl, stopCrawl, uploadFile } from "../lib/api";
import { BrowserViewer } from "./BrowserViewer";
import { CapturedEndpointsPanel } from "./CapturedEndpointsPanel";

interface Props {
  initialUrl?: string;
}

export function AppCrawlPanel({ initialUrl }: Props) {
  const [url, setUrl] = useState(initialUrl ?? "");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [novncUrl, setNovncUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [captureCount, setCaptureCount] = useState(0);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [showCaptured, setShowCaptured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Proxy is decided here, before Launch browser — Chrome's --proxy-server
  // is read once at process start (there's no CDP/Playwright way to change
  // a running browser's proxy), so this can't be a mid-session toggle.
  const [useProxy, setUseProxy] = useState(false);
  const [proxyHost, setProxyHost] = useState("host.docker.internal");
  const [proxyPort, setProxyPort] = useState("8080");
  const [proxyCheck, setProxyCheck] = useState<{ ok: boolean; message: string } | null>(null);
  const [checkingProxy, setCheckingProxy] = useState(false);
  const [activeProxy, setActiveProxy] = useState<string | null>(null);

  async function handleCheckProxy() {
    setCheckingProxy(true);
    setProxyCheck(null);
    try {
      const { reachable, message } = await checkProxyReachable(proxyHost, Number(proxyPort));
      setProxyCheck({ ok: reachable, message });
    } catch (e) {
      setProxyCheck({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setCheckingProxy(false);
    }
  }

  async function handleStart() {
    if (!url) return;
    setLoading(true);
    setError(null);
    try {
      const proxyServer = useProxy && proxyHost && proxyPort ? `${proxyHost}:${proxyPort}` : undefined;
      const { session_id, novnc_url } = await startCrawl(url, proxyServer);
      setSessionId(session_id);
      setNovncUrl(novnc_url);
      setCaptureCount(0);
      setShowCaptured(false);
      setActiveProxy(proxyServer ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleStop() {
    if (!sessionId) return;
    await stopCrawl(sessionId);
    setSessionId(null);
    setNovncUrl(null);
    setShowCaptured(false);
    setActiveProxy(null);
  }

  function handleCapture() {
    setCaptureCount((c) => c + 1);
    setRefreshSignal((s) => s + 1);
  }

  async function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file || !sessionId) return;
    setUploading(true);
    setUploadStatus(null);
    try {
      await uploadFile(sessionId, file);
      setUploadStatus({ kind: "success", message: `Uploaded "${file.name}" to the session's Uploads folder.` });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setUploadStatus({ kind: "error", message: `Failed to upload "${file.name}": ${message}` });
    } finally {
      setUploading(false);
      setTimeout(() => setUploadStatus(null), 6000);
    }
  }

  const hasSession = !!sessionId && !!novncUrl;

  return (
    <div className="panel">
      <h2>App Crawl</h2>
      {!hasSession ? (
        <>
          <div className="row">
            <input
              placeholder="https://app.example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleStart()}
            />
            <button onClick={handleStart} disabled={loading}>
              {loading ? "Launching browser..." : "Launch browser"}
            </button>
          </div>

          <div className="row" style={{ marginTop: 8 }}>
            <label>
              <input type="checkbox" checked={useProxy} onChange={(e) => setUseProxy(e.target.checked)} />{" "}
              Route this session's browser traffic through an intercepting proxy (e.g. Burp Suite)
            </label>
          </div>

          {useProxy && (
            <div className="row" style={{ marginTop: 4, flexWrap: "wrap" }}>
              <input
                placeholder="proxy host (e.g. host.docker.internal)"
                value={proxyHost}
                onChange={(e) => setProxyHost(e.target.value)}
                style={{ width: 240 }}
              />
              <input
                placeholder="port"
                value={proxyPort}
                onChange={(e) => setProxyPort(e.target.value)}
                style={{ width: 70 }}
              />
              <button onClick={handleCheckProxy} disabled={checkingProxy || !proxyHost || !proxyPort}>
                {checkingProxy ? "Checking..." : "Check reachability"}
              </button>
              {proxyCheck && (
                <p className={proxyCheck.ok ? "hint" : "error"} style={{ width: "100%", margin: "4px 0 0" }}>
                  {proxyCheck.ok ? "✓ " : "✗ "}
                  {proxyCheck.message}
                </p>
              )}
              <p className="hint" style={{ width: "100%", margin: "4px 0 0" }}>
                This is fixed for the whole session once launched — to change it later, stop the
                crawl and launch a new one. See Settings for the CA certificate step and address
                guidance for different setups.
              </p>
            </div>
          )}
        </>
      ) : (
        <>
          {/* Kept mounted across the view toggle so its WebSocket/VNC connection
              and running capture count survive switching to the review panel. */}
          <div style={{ display: showCaptured ? "none" : "block" }}>
            <p className="hint">
              Log in and navigate manually if needed, then start the autonomous crawl. If the
              crawler gets stuck it will pause and hand control back to you here. Need to attach
              a file for an upload step in the target app? Use "Attach file" below, then pick it
              from the Uploads folder in the remote browser's file dialog.
            </p>
            {activeProxy && (
              <p className="hint">Routing through proxy: <strong>{activeProxy}</strong></p>
            )}
            <BrowserViewer sessionId={sessionId} novncUrl={novncUrl} onCapture={handleCapture} />
            <div className="row">
              <span>{captureCount} API calls captured</span>
              <div className="spacer" />
              <input
                ref={fileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={handleFileChosen}
              />
              <button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                {uploading ? "Uploading..." : "Attach file"}
              </button>
              <button onClick={() => setShowCaptured(true)}>View captured APIs</button>
              <button onClick={handleStop}>Stop crawl</button>
            </div>
            {uploadStatus && (
              <p className={uploadStatus.kind === "success" ? "hint" : "error"}>
                {uploadStatus.kind === "success" ? "✓ " : "✗ "}
                {uploadStatus.message}
              </p>
            )}
          </div>

          {showCaptured && (
            <CapturedEndpointsPanel
              sessionId={sessionId}
              refreshSignal={refreshSignal}
              onClose={() => setShowCaptured(false)}
            />
          )}
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

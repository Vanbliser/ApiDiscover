import { useState } from "react";
import { startCrawl, stopCrawl } from "../lib/api";
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

  async function handleStart() {
    if (!url) return;
    setLoading(true);
    setError(null);
    try {
      const { session_id, novnc_url } = await startCrawl(url);
      setSessionId(session_id);
      setNovncUrl(novnc_url);
      setCaptureCount(0);
      setShowCaptured(false);
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
  }

  function handleCapture() {
    setCaptureCount((c) => c + 1);
    setRefreshSignal((s) => s + 1);
  }

  const hasSession = !!sessionId && !!novncUrl;

  return (
    <div className="panel">
      <h2>App Crawl</h2>
      {!hasSession ? (
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
      ) : (
        <>
          {/* Kept mounted across the view toggle so its WebSocket/VNC connection
              and running capture count survive switching to the review panel. */}
          <div style={{ display: showCaptured ? "none" : "block" }}>
            <p className="hint">
              Log in and navigate manually if needed, then start the autonomous crawl. If the
              crawler gets stuck it will pause and hand control back to you here.
            </p>
            <BrowserViewer sessionId={sessionId} novncUrl={novncUrl} onCapture={handleCapture} />
            <div className="row">
              <span>{captureCount} API calls captured</span>
              <div className="spacer" />
              <button onClick={() => setShowCaptured(true)}>View captured APIs</button>
              <button onClick={handleStop}>Stop crawl</button>
            </div>
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

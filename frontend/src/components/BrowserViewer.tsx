import { useEffect, useRef, useState } from "react";
import { crawlStreamUrl } from "../lib/api";

interface CapturedRequest {
  method: string;
  url: string;
  status_code: number | null;
}

interface Props {
  sessionId: string;
  novncUrl: string;
  onCapture?: (req: CapturedRequest) => void;
}

type CrawlerStatus =
  | "idle"
  | "manual_control"
  | "autonomous"
  | "stuck_awaiting_input"
  | "finished"
  | "error";

export function BrowserViewer({ sessionId, novncUrl, onCapture }: Props) {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<CrawlerStatus>("manual_control");
  const [captureCount, setCaptureCount] = useState(0);

  useEffect(() => {
    const ws = new WebSocket(crawlStreamUrl(sessionId));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "status") {
        setStatus(msg.status);
      } else if (msg.type === "capture") {
        setCaptureCount((c) => c + 1);
        onCapture?.(msg.data);
      }
    };

    return () => ws.close();
  }, [sessionId]);

  function send(msg: object) {
    wsRef.current?.send(JSON.stringify(msg));
  }

  return (
    <div className="browser-viewer">
      <div className="browser-toolbar">
        <span className={`status-pill status-${status}`}>{status.replace(/_/g, " ")}</span>
        <span className="capture-count">{captureCount} calls captured</span>
        <div className="spacer" />
        {status === "manual_control" || status === "stuck_awaiting_input" ? (
          <button
            onClick={() => send({ type: status === "stuck_awaiting_input" ? "resume_autonomous" : "start_autonomous" })}
          >
            {status === "stuck_awaiting_input" ? "Resume autonomous crawl" : "Start autonomous crawl"}
          </button>
        ) : status === "autonomous" ? (
          <button onClick={() => send({ type: "stop_autonomous" })}>Take manual control</button>
        ) : null}
      </div>
      <iframe
        className="novnc-frame"
        src={novncUrl}
        title="Remote browser"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  crawlStreamUrl,
  deleteSavedSession,
  listSavedSessions,
  resumeSession,
  startCrawl,
  stopCrawl,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubLocation(protocol: string, host: string) {
  vi.stubGlobal("location", { protocol, host, hostname: host.split(":")[0] });
}

describe("WebSocket URLs", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses ws:// and the page's own host on http pages", () => {
    stubLocation("http:", "13.53.168.171:8080");
    expect(crawlStreamUrl("abc")).toBe("ws://13.53.168.171:8080/api/crawl/abc/stream");
  });

  it("uses wss:// on https pages", () => {
    stubLocation("https:", "apidiscover.example.com");
    expect(crawlStreamUrl("abc")).toBe("wss://apidiscover.example.com/api/crawl/abc/stream");
  });

  it("never points at a separate backend port", () => {
    stubLocation("http:", "13.53.168.171:8080");
    expect(crawlStreamUrl("abc")).not.toContain(":8000");
  });
});

describe("HTTP helpers", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("calls the backend with same-origin relative paths", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ sessions: [] }));
    await listSavedSessions();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/crawl/sessions");
  });

  it("sends save_session with the start request", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ session_id: "s1", novnc_url: "/x" }));
    await startCrawl("https://example.com", "proxy:8080", true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/crawl/start");
    expect(JSON.parse(init.body)).toEqual({
      start_url: "https://example.com",
      proxy_server: "proxy:8080",
      save_session: true,
    });
  });

  it("defaults save_session to false", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ session_id: "s1", novnc_url: "/x" }));
    await startCrawl("https://example.com");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).save_session).toBe(false);
  });

  it("lists saved sessions from the response body", async () => {
    const sessions = [
      { session_id: "a", label: "a", start_url: "https://a", created_at: "", updated_at: "", endpoint_count: 2, active: false },
    ];
    fetchMock.mockResolvedValue(jsonResponse({ sessions }));
    expect(await listSavedSessions()).toEqual(sessions);
  });

  it("throws when listing saved sessions fails", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    await expect(listSavedSessions()).rejects.toThrow("500");
  });

  it("surfaces the server's detail message when resume is refused", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "session is already active" }, 409));
    await expect(resumeSession("a")).rejects.toThrow("session is already active");
  });

  it("surfaces the server's detail message when delete is refused", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "cannot delete an active session; stop it first" }, 409));
    await expect(deleteSavedSession("a")).rejects.toThrow("cannot delete an active session");
  });

  it("falls back to the status code when an error has no detail", async () => {
    fetchMock.mockResolvedValue(new Response("not json", { status: 502 }));
    await expect(resumeSession("a")).rejects.toThrow("502");
  });

  it("stops a crawl with a POST to that session", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
    await stopCrawl("abc");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/crawl/abc/stop");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });
});

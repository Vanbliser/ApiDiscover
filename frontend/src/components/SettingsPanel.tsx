import { useEffect, useRef, useState } from "react";
import {
  deleteProxyCaCert,
  getProxyCaCertStatus,
  listProviders,
  upsertProvider,
  uploadProxyCaCert,
  type ProviderConfig,
} from "../lib/api";

interface ExtraField {
  key: string;
  label: string;
  isCookie?: boolean;
}

interface ProviderDef {
  name: string;
  label: string;
  hasApiKey: boolean;
  apiKeyLabel?: string;
  extraFields?: ExtraField[];
}

const PROVIDERS: ProviderDef[] = [
  { name: "crt_sh", label: "crt.sh (passive, no key)", hasApiKey: false },
  { name: "dns_bruteforce", label: "DNS brute-force (active, no key)", hasApiKey: false },
  { name: "shodan", label: "Shodan", hasApiKey: true },
  { name: "censys", label: "Censys", hasApiKey: true },
  { name: "securitytrails", label: "SecurityTrails", hasApiKey: true },
  { name: "virustotal", label: "VirusTotal", hasApiKey: true },
  {
    name: "wallarm",
    label: "Wallarm",
    hasApiKey: true,
    apiKeyLabel: "Token",
    extraFields: [
      { key: "client_id", label: "Client ID" },
      { key: "api_host", label: "API host (default us1.api.wallarm.com)" },
      { key: "wsess", label: "wsess cookie", isCookie: true },
    ],
  },
];

interface FormState {
  enabled: boolean;
  apiKey: string;
  extra: Record<string, string>;
  cookies: Record<string, string>;
}

function emptyForm(provider: ProviderDef): FormState {
  return {
    enabled: !provider.hasApiKey,
    apiKey: "",
    extra: {},
    cookies: {},
  };
}

function formFromConfig(config: ProviderConfig): FormState {
  return {
    enabled: config.enabled,
    apiKey: config.api_key ?? "",
    extra: { ...config.extra },
    cookies: { ...config.cookies },
  };
}

export function SettingsPanel() {
  const [forms, setForms] = useState<Record<string, FormState>>({});
  const [savedFlash, setSavedFlash] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function loadConfig() {
    setLoadError(null);
    try {
      const configs = await listProviders();
      const byName: Record<string, ProviderConfig> = {};
      for (const c of configs) byName[c.name] = c;

      setForms(
        Object.fromEntries(
          PROVIDERS.map((p) => [p.name, byName[p.name] ? formFromConfig(byName[p.name]) : emptyForm(p)])
        )
      );
      setLoaded(true);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    loadConfig();
  }, []);

  function updateForm(name: string, patch: Partial<FormState>) {
    setForms((s) => ({ ...s, [name]: { ...s[name], ...patch } }));
  }

  function updateExtraField(name: string, key: string, value: string) {
    setForms((s) => ({ ...s, [name]: { ...s[name], extra: { ...s[name].extra, [key]: value } } }));
  }

  function updateCookieField(name: string, key: string, value: string) {
    setForms((s) => ({ ...s, [name]: { ...s[name], cookies: { ...s[name].cookies, [key]: value } } }));
  }

  async function handleSave(provider: ProviderDef) {
    const form = forms[provider.name];
    await upsertProvider(provider.name, form.enabled, form.apiKey, form.cookies, form.extra);
    setSavedFlash(provider.name);
    setTimeout(() => setSavedFlash(null), 1500);
  }

  if (!loaded) {
    return (
      <div className="panel">
        <h2>Recon Provider Settings</h2>
        {loadError ? (
          <>
            <p className="error">Failed to load settings: {loadError}</p>
            <button onClick={loadConfig}>Retry</button>
          </>
        ) : (
          <p className="hint">Loading saved settings...</p>
        )}
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Recon Provider Settings</h2>
      <p className="hint">
        Values are encrypted at rest but shown here in plain text for convenience, since this runs
        locally. Settings persist across navigation and are applied the next time you run recon.
      </p>

      <div className="provider-grid">
        {PROVIDERS.map((p) => {
          const form = forms[p.name];
          if (!form) return null;
          return (
            <div className="provider-grid-row" key={p.name}>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => updateForm(p.name, { enabled: e.target.checked })}
              />
              <span className="provider-name">{p.label}</span>
              <div className="provider-fields">
                {p.hasApiKey && (
                  <input
                    type="text"
                    placeholder={p.apiKeyLabel ?? "API key"}
                    value={form.apiKey}
                    onChange={(e) => updateForm(p.name, { apiKey: e.target.value })}
                  />
                )}
                {p.extraFields?.map((field) => (
                  <input
                    key={field.key}
                    type="text"
                    placeholder={field.label}
                    value={(field.isCookie ? form.cookies[field.key] : form.extra[field.key]) ?? ""}
                    onChange={(e) =>
                      field.isCookie
                        ? updateCookieField(p.name, field.key, e.target.value)
                        : updateExtraField(p.name, field.key, e.target.value)
                    }
                  />
                ))}
              </div>
              <button onClick={() => handleSave(p)}>{savedFlash === p.name ? "Saved" : "Save"}</button>
            </div>
          );
        })}
      </div>

      <ProxyCaCertSettings />
    </div>
  );
}

function ProxyCaCertSettings() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      const { configured } = await getProxyCaCertStatus();
      setConfigured(configured);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await uploadProxyCaCert(file);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove() {
    setBusy(true);
    setError(null);
    try {
      await deleteProxyCaCert();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel" style={{ marginTop: 24 }}>
      <h2>Intercepting Proxy (Burp Suite) CA Certificate</h2>
      <p className="hint">
        Lets the remote browser trust an intercepting proxy's TLS certificate (e.g. Burp Suite's),
        so HTTPS sites load cleanly while a crawl session routes its traffic through the proxy for
        inspection. This only affects <strong>new</strong> crawl sessions started after uploading —
        it's imported into the browser's trust store once, when that session's container starts,
        so an already-running session needs to be stopped and restarted to pick up a change here.
      </p>

      {configured === null ? (
        <p className="hint">Loading...</p>
      ) : configured ? (
        <p>
          ✓ A CA certificate is configured.{" "}
          <button onClick={handleRemove} disabled={busy}>
            {busy ? "Removing..." : "Remove"}
          </button>
        </p>
      ) : (
        <p className="hint">No CA certificate configured — new sessions will show certificate warnings if you route them through a proxy.</p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".pem,.crt,.cer"
        style={{ display: "none" }}
        onChange={handleFileChosen}
      />
      <button onClick={() => fileInputRef.current?.click()} disabled={busy}>
        {busy ? "Uploading..." : configured ? "Replace certificate" : "Upload certificate (.pem)"}
      </button>{" "}
      <button onClick={() => setShowGuide((s) => !s)}>
        {showGuide ? "Hide setup guide" : "How do I get Burp's CA cert, and how do I point a session at Burp?"}
      </button>

      {error && <p className="error">{error}</p>}

      {showGuide && <ProxySetupGuide />}
    </div>
  );
}

function ProxySetupGuide() {
  return (
    <div className="hint" style={{ marginTop: 12, lineHeight: 1.6 }}>
      <p>
        <strong>Getting Burp's CA certificate:</strong> in Burp, go to Proxy → Proxy settings →
        Import / export CA certificate → Certificate in DER format (or use the built-in "CA
        Certificate" download at{" "}
        <code>http://burp</code> while your browser is proxied through Burp). Upload the resulting
        file above — PEM or DER both work.
      </p>
      <p>
        <strong>What address to point a session at</strong> depends on where this app's backend and
        Docker are running relative to where Burp itself runs:
      </p>
      <p>
        <strong>1. Same machine</strong> (backend, Docker, and Burp all on your laptop): use{" "}
        <code>host.docker.internal:&lt;burp-port&gt;</code> (Docker Desktop's built-in address for
        reaching the host machine from inside a container). Burp's listener can stay bound to{" "}
        <code>127.0.0.1</code> — no other setup needed.
      </p>
      <p>
        <strong>2. Backend runs remotely, Burp stays on your laptop</strong>: your laptop usually
        has no stable, directly-reachable address (NAT/CGNAT, changing IP). Don't try to use your
        laptop's public IP directly — instead create a tunnel <em>from</em> your laptop{" "}
        <em>to</em> the remote backend server, and point the session at the tunnel's address on
        that server:
      </p>
      <ul>
        <li>
          Already using Tailscale/WireGuard or another mesh VPN? Just use your laptop's VPN IP —
          simplest option if available.
        </li>
        <li>
          Otherwise, an SSH reverse tunnel works without extra software:{" "}
          <code>ssh -R 127.0.0.1:8080:localhost:8080 user@remote-backend-host</code> (run from your
          laptop, while Burp listens on port 8080 there) — then use <code>localhost:8080</code> as
          the proxy address <em>from the remote server's point of view</em>. Keep the{" "}
          <code>127.0.0.1:</code> prefix exactly as shown if this backend is internet-facing —
          dropping it can expose Burp to anyone who finds the remote server's IP.{" "}
          <SshTunnelDetails />
        </li>
      </ul>
      <p>
        <strong>3. Burp runs on a remote server with a public/static address</strong>: use that
        server's address directly, e.g. <code>1.2.3.4:8080</code>. Bind Burp's listener to{" "}
        <code>0.0.0.0</code> (or the specific interface) instead of the default{" "}
        <code>127.0.0.1</code> so it actually accepts connections from elsewhere — and firewall
        that port to only the backend's IP (or the specific IPs of machines that need it), since
        this makes Burp reachable over a real network rather than just loopback. If this app's own
        backend is internet-facing, treat that firewall rule as load-bearing, not optional — the
        same reachability that lets the backend route traffic to Burp is reachability anyone else
        could probe for too if the rule is too broad.
      </p>
      <p>
        Whichever case applies, use the "Check reachability" button on the App Crawl launch form
        before clicking Launch browser — it tests the exact address from inside a container on
        this Docker network. The proxy address is fixed for the life of a session once launched
        (Chrome reads it once at startup and it can't be changed on a running browser), so this is
        the one moment to catch a wrong address before committing to it.
      </p>
    </div>
  );
}

function SshTunnelDetails() {
  const [open, setOpen] = useState(false);
  return (
    <span>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: "inherit",
          textDecoration: "underline",
          cursor: "pointer",
          font: "inherit",
        }}
      >
        {open ? "Hide details" : "See details"}
      </button>
      {open && (
        <div style={{ marginTop: 8, paddingLeft: 12, borderLeft: "2px solid currentColor", opacity: 0.9 }}>
          <p>
            <strong>The setup:</strong> your laptop runs Burp, listening on{" "}
            <code>127.0.0.1:8080</code> (only accepts connections from itself). The remote server
            runs this app's backend and needs to send crawl traffic to Burp. The remote server
            can't connect to your laptop directly — laptops usually sit behind NAT/CGNAT with no
            stable address reachable from outside. So the direction is flipped: your laptop
            initiates a connection <em>to</em> the remote server, and that connection becomes a
            tunnel the remote server can use to reach back to Burp.
          </p>
          <p>
            <strong>What the command does:</strong> running{" "}
            <code>ssh -R 127.0.0.1:8080:localhost:8080 user@remote-backend-host</code> from your
            laptop opens a normal SSH session, and the <code>-R</code> flag tells the remote
            server "open port 8080 on yourself, and forward any connection that arrives there back
            through this SSH connection to <code>localhost:8080</code> on my end" (where Burp is
            listening). Now something is listening on port 8080 on the remote server, and anything
            that connects to it ends up talking to Burp on your laptop. That's why the app's proxy
            address field gets set to <code>localhost:8080</code> — from the remote server's own
            point of view, that's where "Burp" now appears to live, since that's the tunnel
            entrance.
          </p>
          <p>
            <strong>What the <code>127.0.0.1:</code> prefix changes:</strong> the full syntax of{" "}
            <code>-R</code> is <code>-R [bind_address:]port:host:port</code>. The leading{" "}
            <code>127.0.0.1:</code> is the bind address <em>on the remote server</em> — it controls
            who on the remote server's network can connect to the tunnel entrance.
          </p>
          <ul>
            <li>
              <strong>With it</strong> (as shown above): the tunnel entrance only accepts
              connections from the remote server itself — only processes running on that same
              server (like this app's backend) can use it to reach Burp. Nobody outside that
              server can touch port 8080 on it at all.
            </li>
            <li>
              <strong>Without it</strong> (just <code>-R 8080:localhost:8080</code>): SSH's
              default server-side setting (<code>GatewayPorts</code>) can bind that tunnel
              entrance to all interfaces on the remote server, including its public one. If that
              default is in play, anyone on the internet who knows the remote server's IP could
              connect to <code>&lt;remote-server-ip&gt;:8080</code> directly and land inside your
              tunnel, reaching Burp on your laptop — completely bypassing this app and any of its
              own access controls.
            </li>
          </ul>
          <p>
            <strong>Why it matters more for an internet-facing deployment:</strong> when the
            backend was only reachable over a private/trusted network, a slightly-too-open port
            was a smaller risk — the pool of people who could even attempt to reach it was already
            limited. Once the backend is reachable from the open internet, the same small
            misconfiguration means literally anyone could reach it, not just people your team
            trusts. Always include the <code>127.0.0.1:</code> prefix in this command when the
            remote server is internet-facing — it costs nothing and closes off a path into Burp
            that has nothing to do with whether this app itself is secure.
          </p>
        </div>
      )}
    </span>
  );
}

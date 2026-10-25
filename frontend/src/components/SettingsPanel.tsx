import { useEffect, useRef, useState } from "react";
import { deleteProxyCaCert, getProxyCaCertStatus, uploadProxyCaCert } from "../lib/api";

export function SettingsPanel() {
  return <ProxyCaCertSettings />;
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
    <div className="panel">
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
        has no address the server can reach, so the connection has to start from your laptop.
        Enter <code>host.docker.internal:8080</code> as the proxy address, and open a tunnel from
        your laptop that makes Burp reachable on the server's Docker bridge:
      </p>
      <ul>
        <li>
          Already using Tailscale/WireGuard or another mesh VPN? Point Burp at your laptop's VPN
          address instead, if the server can reach it. That's the simplest option.
        </li>
        <li>
          Otherwise, run this on your laptop, with Burp listening on <code>127.0.0.1:8080</code>:{" "}
          <code>ssh -N -R 172.17.0.1:8080:localhost:8080 user@remote-backend-host</code>. Here{" "}
          <code>172.17.0.1</code> is the server's Docker bridge address (check it with{" "}
          <code>ip -4 addr show docker0</code>). This needs{" "}
          <code>GatewayPorts clientspecified</code> in the server's sshd config. Note that{" "}
          <code>172.17.0.1</code> works for only Linux remote host.{" "}
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
            <strong>The setup:</strong> Burp runs on your laptop, listening on{" "}
            <code>127.0.0.1:8080</code>, so it accepts connections only from the laptop itself. The
            session containers run on the server and need to reach Burp. The server can't connect
            to your laptop directly, because laptops sit behind NAT with no stable address. So the
            tunnel is opened from the laptop <em>to</em> the server.
          </p>
          <p>
            <strong>What the command does:</strong> <code>-R 172.17.0.1:8080:localhost:8080</code>{" "}
            tells the server to listen on <code>172.17.0.1:8080</code> and forward anything that
            arrives there back through the SSH connection to Burp on your laptop.
          </p>
          <p>
            <strong>Why the Docker bridge address:</strong> containers reach the host through the
            bridge, not through the server's loopback. <code>host.docker.internal</code> resolves to
            that bridge address on Linux, so a listener on <code>127.0.0.1</code> on the server
            would be invisible to the containers.
          </p>
          <p>
            <strong>Why it isn't exposed:</strong> the bridge address is not on the server's public
            interface. Only the host and containers on that bridge can reach it. Keep{" "}
            <code>GatewayPorts clientspecified</code> rather than <code>yes</code>: with{" "}
            <code>yes</code>, sshd binds forwarded ports on every interface, including the public
            one, and anyone who finds the server's address could reach Burp through the tunnel.
          </p>
          <p>
            <strong>On macOS:</strong> Docker Desktop has no bridge address to bind to, but the same{" "}
            <code>host.docker.internal:8080</code> proxy address works. Run{" "}
            <code>ssh -N -R 8080:localhost:8080 user@host</code> against a local SSH server, as in
            the local test steps. For Windows remote host, you will have to run{" "}
            <code>ipconfig</code> and look for the "vEthernet (WSL)", vEthernet (DockerNAT) 
            or vEthernet (Default Switch) adapter's IPv4 address, and use that IP address
          </p>
        </div>
      )}
    </span>
  );
}

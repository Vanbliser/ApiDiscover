import { useState } from "react";
import { upsertProvider } from "../lib/api";

interface ExtraField {
  key: string;
  label: string;
  isCookie?: boolean;
  secret?: boolean;
}

interface ProviderDef {
  name: string;
  label: string;
  hasApiKey: boolean;
  apiKeyLabel?: string;
  extraFields?: ExtraField[];
}

const PROVIDERS: ProviderDef[] = [
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
      { key: "api_host", label: "API host (optional, default us1.api.wallarm.com)" },
      { key: "wsess", label: "wsess cookie", isCookie: true, secret: true },
    ],
  },
  { name: "dns_bruteforce", label: "DNS brute-force (active, no key)", hasApiKey: false },
];

export function SettingsPanel() {
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [extraValues, setExtraValues] = useState<Record<string, Record<string, string>>>({});
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<string | null>(null);

  function setExtraField(providerName: string, key: string, value: string) {
    setExtraValues((s) => ({
      ...s,
      [providerName]: { ...(s[providerName] ?? {}), [key]: value },
    }));
  }

  async function handleSave(provider: ProviderDef) {
    const fields = extraValues[provider.name] ?? {};
    const cookies: Record<string, string> = {};
    const extra: Record<string, string> = {};

    for (const field of provider.extraFields ?? []) {
      const value = fields[field.key] ?? "";
      if (field.isCookie) cookies[field.key] = value;
      else extra[field.key] = value;
    }

    await upsertProvider(provider.name, enabled[provider.name] ?? true, apiKeys[provider.name] ?? "", cookies, extra);
    setSaved(provider.name);
    setTimeout(() => setSaved(null), 1500);
  }

  return (
    <div className="panel">
      <h2>Recon Provider Settings</h2>
      <p className="hint">
        API keys and cookies are encrypted at rest. Providers without required credentials set are
        skipped during recon runs.
      </p>
      {PROVIDERS.map((p) => (
        <div className="provider-config" key={p.name}>
          <div className="provider-row">
            <label className="provider-toggle">
              <input
                type="checkbox"
                checked={enabled[p.name] ?? true}
                onChange={(e) => setEnabled((s) => ({ ...s, [p.name]: e.target.checked }))}
              />
              {p.label}
            </label>
            {p.hasApiKey && (
              <input
                type="password"
                placeholder={p.apiKeyLabel ?? "API key"}
                value={apiKeys[p.name] ?? ""}
                onChange={(e) => setApiKeys((s) => ({ ...s, [p.name]: e.target.value }))}
              />
            )}
            <button onClick={() => handleSave(p)}>{saved === p.name ? "Saved" : "Save"}</button>
          </div>
          {p.extraFields && p.extraFields.length > 0 && (
            <div className="provider-extra-fields">
              {p.extraFields.map((field) => (
                <input
                  key={field.key}
                  type={field.secret ? "password" : "text"}
                  placeholder={field.label}
                  value={extraValues[p.name]?.[field.key] ?? ""}
                  onChange={(e) => setExtraField(p.name, field.key, e.target.value)}
                />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

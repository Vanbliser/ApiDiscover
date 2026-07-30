import { useEffect, useState } from "react";
import { listProviders, upsertProvider, type ProviderConfig } from "../lib/api";

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
    </div>
  );
}

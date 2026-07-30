import { useState } from "react";
import { ReconPanel } from "./components/ReconPanel";
import { AppCrawlPanel } from "./components/AppCrawlPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import "./index.css";

type View = "home" | "settings";

function App() {
  const [view, setView] = useState<View>("home");
  const [crawlTarget, setCrawlTarget] = useState<string | undefined>(undefined);

  return (
    <div className="app">
      <header>
        <h1>ApiDiscover</h1>
        <nav>
          <button className={view === "home" ? "active" : ""} onClick={() => setView("home")}>
            Home
          </button>
          <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}>
            Settings
          </button>
        </nav>
      </header>

      <main>
        {/* Both views stay mounted so switching to Settings and back doesn't
            tear down the recon WebSocket, in-flight crawl, or browser viewer. */}
        <div style={{ display: view === "home" ? "block" : "none" }}>
          <ReconPanel onSelectTarget={setCrawlTarget} />
          <AppCrawlPanel initialUrl={crawlTarget} />
        </div>
        <div style={{ display: view === "settings" ? "block" : "none" }}>
          <SettingsPanel />
        </div>
      </main>
    </div>
  );
}

export default App;

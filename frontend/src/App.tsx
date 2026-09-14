import { useEffect, useState } from "react";
import { HashRouter, Link, Route, Routes } from "react-router-dom";
import { getMe } from "./api";
import Home from "./pages/Home";
import Developer from "./pages/Developer";
import type { MeIdentity } from "./types";

function TopBar() {
  const [me, setMe] = useState<MeIdentity | null>(null);
  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <span className="brand-mark">▾</span> TRACE
      </Link>
      <nav className="topbar-links">
        {me ? (
          <Link to="/me" className="me-link">
            My Profile
          </Link>
        ) : (
          <Link to="/auth/github">Connect GitHub</Link>
        )}
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <HashRouter>
      <div className="app">
        <TopBar />
        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/me" element={<Developer self />} />
            <Route path="/developers/:username" element={<Developer />} />
            <Route path="*" element={<Home />} />
          </Routes>
        </main>
        <footer className="footer">
          deterministic domain inference · scores are evidence signals, not
          verified expertise
        </footer>
      </div>
    </HashRouter>
  );
}
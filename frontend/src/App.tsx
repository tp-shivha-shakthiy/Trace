import { useEffect, useState } from "react";
import { HashRouter, Link, Route, Routes } from "react-router-dom";
import { getMe } from "./api";
import Home from "./pages/Home";
import Developer from "./pages/Developer";
import type { MeIdentity } from "./types";

function TopBar({ me }: { me: MeIdentity | null }) {
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
          // /auth/github is a backend route; a full-page anchor (not a
          // HashRouter <Link>, which would stay client-side) starts OAuth.
          <a href="/auth/github">Connect GitHub</a>
        )}
      </nav>
    </header>
  );
}

export default function App() {
  const [me, setMe] = useState<MeIdentity | null>(null);

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);

  return (
    <HashRouter>
      <div className="app">
        <TopBar me={me} />
        <main className="content">
          <Routes>
            <Route path="/" element={<Home meUsername={me?.username} />} />
            <Route path="/me" element={<Developer self />} />
            <Route path="/developers/:username" element={<Developer />} />
            <Route path="*" element={<Home meUsername={me?.username} />} />
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
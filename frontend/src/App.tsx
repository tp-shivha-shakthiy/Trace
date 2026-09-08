import { HashRouter, Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Developer from "./pages/Developer";

export default function App() {
  return (
    <HashRouter>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">
            <span className="brand-mark">▾</span> TRACE
          </Link>
          <nav className="topbar-links">
            <Link to="/auth/github">Connect GitHub</Link>
          </nav>
        </header>
        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
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
import Link from "next/link";
import fa from "@/locales/fa.json";

export default function Home() {
  return (
    <main className="auth-card">
      <div className="logo">
        <b>{fa.nav.logo}</b> <span className="tick">◆</span>
        <small>{fa.nav.subtitle}</small>
      </div>
      <div className="gold-rule" aria-hidden="true" />
      <h1>{fa.app.title}</h1>
      <p className="muted">{fa.app.tagline}</p>
      <div className="actions">
        <Link className="btn primary" href="/login">
          {fa.app.go_login}
        </Link>
        <Link className="btn" href="/register">
          {fa.app.go_register}
        </Link>
      </div>
      <div className="status-line">
        <span className="dot" aria-hidden="true" />
        {fa.app.status_ok} · {fa.app.milestone}
      </div>
    </main>
  );
}

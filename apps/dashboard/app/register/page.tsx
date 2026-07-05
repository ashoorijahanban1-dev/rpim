"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import fa from "@/locales/fa.json";
import { api, setToken } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, tenant_name: tenantName }),
      });
      if (resp.status === 409) {
        setError(fa.auth.error_conflict);
        return;
      }
      if (!resp.ok) {
        setError(fa.auth.error_generic);
        return;
      }
      const body = await resp.json();
      setToken(body.access_token);
      router.push("/onboarding");
    } catch {
      setError(fa.auth.error_generic);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{fa.auth.register_title}</h1>
      <form onSubmit={submit}>
        <label>
          {fa.auth.tenant_name}
          <input
            type="text"
            value={tenantName}
            onChange={(e) => setTenantName(e.target.value)}
            required
          />
        </label>
        <label>
          {fa.auth.email}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            dir="ltr"
          />
        </label>
        <label>
          {fa.auth.password}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            dir="ltr"
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy}>
          {fa.auth.register_cta}
        </button>
      </form>
      <p>
        <Link href="/login">{fa.auth.have_account}</Link>
      </p>
    </main>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import fa from "@/locales/fa.json";
import { api } from "@/lib/api";

const FIELDS = ["goal", "audience", "channel", "format", "hook", "cta"] as const;

export default function NewBriefPage() {
  const router = useRouter();
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await api("/content/drafts", {
        method: "POST",
        body: JSON.stringify({
          brief: {
            goal: values.goal,
            audience: values.audience,
            channel: values.channel,
            format: values.format,
            hook: values.hook || null,
            cta: values.cta || null,
          },
        }),
      });
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        setError(fa.auth.error_generic);
        return;
      }
      setDone(true);
    } catch {
      setError(fa.auth.error_generic);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{fa.brief.title}</h1>
      <form onSubmit={submit}>
        {FIELDS.map((field) => (
          <label key={field}>
            {fa.brief[field]}
            <input
              type="text"
              required={field !== "hook" && field !== "cta"}
              value={values[field] ?? ""}
              onChange={(e) => setValues({ ...values, [field]: e.target.value })}
            />
          </label>
        ))}
        {error && <p role="alert">{error}</p>}
        {done && (
          <p role="status">
            {fa.brief.created} <Link href="/queue">{fa.queue.title}</Link>
          </p>
        )}
        <button type="submit" disabled={busy}>
          {fa.brief.submit}
        </button>
      </form>
    </main>
  );
}

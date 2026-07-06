"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";

type QaFlag = { check: string; level: string; reason: string };
type Draft = {
  draft_id: string;
  text: string;
  status: string;
  flag_unsourced: boolean;
  brief: Record<string, string | null>;
  qa: { flags: QaFlag[]; requires_human: boolean } | null;
};

export default function QueuePage() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const resp = await api("/content/drafts?status=draft");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    const body = await resp.json();
    setDrafts(body.drafts);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setDrafts([]));
  }, [router, load]);

  async function runQa(id: string) {
    const resp = await api(`/qa/check/${id}`, { method: "POST" });
    if (!resp.ok) return;
    const qa = await resp.json();
    setDrafts((ds) => (ds ?? []).map((d) => (d.draft_id === id ? { ...d, qa } : d)));
  }

  async function approve(id: string) {
    await api(`/content/drafts/${id}/approve`, { method: "POST" });
    await load();
  }

  async function saveEdit(id: string) {
    const text = edits[id];
    if (!text?.trim()) return;
    await api(`/content/drafts/${id}`, {
      method: "PUT",
      body: JSON.stringify({ edited_text: text }),
    });
    await load();
  }

  async function reject(id: string) {
    await api(`/content/drafts/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({
        reason_code: reasons[id] ?? "taste",
        note: notes[id] || null,
      }),
    });
    await load();
  }

  if (drafts === null) return <main>{fa.queue.loading}</main>;

  const reasonEntries = Object.entries(fa.queue.reasons);

  return (
    <main>
      <h1>{fa.queue.title}</h1>
      <p>
        <Link href="/briefs/new">{fa.queue.new_draft}</Link>
      </p>
      {drafts.length === 0 && <p>{fa.queue.empty}</p>}
      {drafts.map((d) => (
        <section key={d.draft_id}>
          <p>{d.text}</p>
          {d.flag_unsourced && <p>{fa.queue.flag_unsourced}</p>}
          {d.qa?.requires_human && <p role="alert">{fa.queue.qa_requires_human}</p>}
          {d.qa?.flags.map((f, i) => (
            <p key={i}>{fa.queue.flag_prefix}{f.reason}</p>
          ))}
          <div>
            <button onClick={() => approve(d.draft_id)}>{fa.queue.approve}</button>
            <button onClick={() => runQa(d.draft_id)}>{fa.queue.qa_run}</button>
          </div>
          <textarea
            rows={4}
            placeholder={fa.queue.edit_placeholder}
            value={edits[d.draft_id] ?? d.text}
            onChange={(e) => setEdits({ ...edits, [d.draft_id]: e.target.value })}
          />
          <button onClick={() => saveEdit(d.draft_id)}>{fa.queue.edit_save}</button>
          <div>
            <label>
              {fa.queue.reject_reason}
              <select
                value={reasons[d.draft_id] ?? "taste"}
                onChange={(e) => setReasons({ ...reasons, [d.draft_id]: e.target.value })}
              >
                {reasonEntries.map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <input
              type="text"
              placeholder={fa.queue.note}
              value={notes[d.draft_id] ?? ""}
              onChange={(e) => setNotes({ ...notes, [d.draft_id]: e.target.value })}
            />
            <button onClick={() => reject(d.draft_id)}>{fa.queue.reject}</button>
          </div>
        </section>
      ))}
    </main>
  );
}

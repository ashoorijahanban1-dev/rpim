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
  created_at: string;
  brief: Record<string, string | null>;
  qa: { flags: QaFlag[]; requires_human: boolean } | null;
};

function faNum(n: number): string {
  return n.toLocaleString("fa-IR");
}

// Relative time, all strings from locales/fa.json. API timestamps are
// timezone-aware ISO; normalize defensively if the offset is missing.
function relativeTime(iso: string): string {
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const then = Date.parse(normalized);
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - then) / 60_000));
  if (minutes < 1) return fa.time.just_now;
  if (minutes < 60) return fa.time.minutes_ago.replace("{n}", faNum(minutes));
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return fa.time.hours_ago.replace("{n}", faNum(hours));
  const days = Math.floor(hours / 24);
  if (days === 1) return fa.time.yesterday;
  return fa.time.days_ago.replace("{n}", faNum(days));
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export default function QueuePage() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [sentThisMonth, setSentThisMonth] = useState<number | null>(null);

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
    // Compact stats: sent count for the current month (existing endpoint).
    api(`/reports/monthly?month=${encodeURIComponent(currentMonth())}`)
      .then(async (resp) => {
        if (!resp.ok) return;
        const report = await resp.json();
        setSentThisMonth(report.publish.sent);
      })
      .catch(() => {});
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

  function startEdit(d: Draft) {
    setEdits((e) => ({ ...e, [d.draft_id]: e[d.draft_id] ?? d.text }));
    setEditing((e) => ({ ...e, [d.draft_id]: true }));
  }

  function cancelEdit(id: string) {
    setEditing((e) => ({ ...e, [id]: false }));
    setEdits((e) => {
      const rest = { ...e };
      delete rest[id];
      return rest;
    });
  }

  async function saveEdit(id: string) {
    const text = edits[id];
    if (!text?.trim()) return;
    await api(`/content/drafts/${id}`, {
      method: "PUT",
      body: JSON.stringify({ edited_text: text }),
    });
    setEditing((e) => ({ ...e, [id]: false }));
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

  if (drafts === null) {
    return (
      <main>
        <p className="muted">{fa.queue.loading}</p>
      </main>
    );
  }

  const reasonEntries = Object.entries(fa.queue.reasons);

  function cardTone(d: Draft): string {
    if (d.qa?.requires_human) return "blocked";
    if (d.flag_unsourced || editing[d.draft_id]) return "warned";
    return "ready";
  }

  function statusChip(d: Draft) {
    if (d.qa?.requires_human) {
      return (
        <span className="chip danger" role="alert">
          {fa.queue.qa_requires_human}
        </span>
      );
    }
    if (editing[d.draft_id]) {
      return <span className="chip warn">{fa.queue.editing}</span>;
    }
    if (d.flag_unsourced) {
      return <span className="chip warn">{fa.queue.flag_unsourced}</span>;
    }
    if (d.qa) {
      return <span className="chip ok">{fa.queue.qa_passed}</span>;
    }
    return <span className="chip plain">{fa.queue.qa_pending}</span>;
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{fa.queue.title}</h1>
          <p>
            {drafts.length > 0
              ? fa.queue.subtitle_count.replace("{count}", faNum(drafts.length))
              : fa.queue.subtitle_empty}
          </p>
        </div>
        <Link className="btn primary" href="/briefs/new">
          {fa.queue.new_draft}
        </Link>
      </header>

      <div className="stats">
        <div className="stat">
          <div className="k">{fa.queue.stat_pending}</div>
          <div className="v">{faNum(drafts.length)}</div>
        </div>
        {sentThisMonth !== null && (
          <div className="stat">
            <div className="k">{fa.queue.stat_sent_month}</div>
            <div className="v">{faNum(sentThisMonth)}</div>
          </div>
        )}
      </div>

      <div className="qhead">
        <h2>{fa.queue.list_heading}</h2>
        <span className="rule" aria-hidden="true" />
      </div>

      {drafts.length === 0 && (
        <section className="empty-state">
          <p>{fa.queue.empty}</p>
          <Link className="btn primary" href="/briefs/new">
            {fa.queue.new_draft}
          </Link>
        </section>
      )}

      <div className="queue">
        {drafts.map((d) => (
          <section key={d.draft_id} className={`card ${cardTone(d)}`}>
            <div className="meta">
              {statusChip(d)}
              {d.brief.channel && <span className="chip plain">{d.brief.channel}</span>}
              <span>
                {d.brief.goal ? `${fa.queue.brief_prefix}${d.brief.goal} · ` : ""}
                {relativeTime(d.created_at)}
              </span>
            </div>

            {d.qa && d.qa.flags.length > 0 && (
              <div className="qa-box">
                {d.qa.flags.map((f, i) => (
                  <div key={i}>
                    {fa.queue.flag_prefix}
                    {f.reason}
                  </div>
                ))}
              </div>
            )}

            {editing[d.draft_id] ? (
              <>
                <textarea
                  rows={4}
                  placeholder={fa.queue.edit_placeholder}
                  value={edits[d.draft_id] ?? d.text}
                  onChange={(e) => setEdits({ ...edits, [d.draft_id]: e.target.value })}
                />
                <div className="actions">
                  <button className="btn primary" onClick={() => saveEdit(d.draft_id)}>
                    {fa.queue.edit_save}
                  </button>
                  <button className="btn" onClick={() => cancelEdit(d.draft_id)}>
                    {fa.queue.edit_cancel}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text">{d.text}</p>
                <div className="actions">
                  <button className="btn primary" onClick={() => approve(d.draft_id)}>
                    {fa.queue.approve}
                  </button>
                  <button className="btn" onClick={() => startEdit(d)}>
                    {fa.queue.edit}
                  </button>
                  <button className="btn" onClick={() => runQa(d.draft_id)}>
                    {fa.queue.qa_run}
                  </button>
                  <span className="sep" />
                  <select
                    aria-label={fa.queue.reject_reason}
                    value={reasons[d.draft_id] ?? "taste"}
                    onChange={(e) => setReasons({ ...reasons, [d.draft_id]: e.target.value })}
                  >
                    {reasonEntries.map(([code, label]) => (
                      <option key={code} value={code}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder={fa.queue.note}
                    value={notes[d.draft_id] ?? ""}
                    onChange={(e) => setNotes({ ...notes, [d.draft_id]: e.target.value })}
                  />
                  <button className="btn ghost-danger" onClick={() => reject(d.draft_id)}>
                    {fa.queue.reject}
                  </button>
                </div>
              </>
            )}
          </section>
        ))}
      </div>
    </main>
  );
}

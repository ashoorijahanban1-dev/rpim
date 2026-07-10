"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken, readErrorDetail } from "@/lib/api";
import { faDateTime, faNum, relativeTime } from "@/lib/format";

// Shapes confirmed against core-api routers/publish.py, content.py and
// qa_governance.py:
// POST /publish/jobs {draft_id, channel, chat_id, campaign_code,
//   scheduled_at?, landing_url?, image?: {template, size}} →
//   {job_id, status, utm, landing_url, image_spec};
// GET /publish/jobs → {jobs: [...]}; GET /governance/status → {silence, kill};
// GET /content/drafts?status=... accepts ONE status per query → fetch
// approved and edited separately, then merge.
type Draft = {
  draft_id: string;
  text: string;
  status: string;
  created_at: string;
};

type Job = {
  job_id: string;
  draft_id: string;
  channel: string;
  chat_id: string;
  campaign_code: string;
  utm: Record<string, string>;
  landing_url: string | null;
  image_spec: { template: string; size: string } | null;
  status: string;
  attempts: number;
  scheduled_at: string | null;
  sent_at: string | null;
  created_at: string;
};

type JobCreated = {
  job_id: string;
  status: string;
  utm: Record<string, string>;
};

type Governance = { silence: boolean; kill: boolean };

const CHANNELS = ["telegram", "bale", "eitaa"] as const;
const IMAGE_TEMPLATES = ["announce", "quote", "product"] as const;
const IMAGE_SIZES = ["square", "story", "wide"] as const;

function channelLabel(channel: string): string {
  const labels: Record<string, string> = fa.publish.channels;
  return labels[channel] ?? channel;
}

function statusLabel(status: string): string {
  if (status === "queued") return fa.publish.status_queued;
  if (status === "sent") return fa.publish.status_sent;
  return status;
}

function draftLabel(d: Draft): string {
  const status =
    d.status === "edited" ? fa.publish.draft_status_edited : fa.publish.draft_status_approved;
  const text = d.text.length > 60 ? `${d.text.slice(0, 60)}…` : d.text;
  return `${status} — ${text}`;
}

function formatUtm(utm: Record<string, string>): string {
  return Object.entries(utm)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
}

export default function PublishPage() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [governance, setGovernance] = useState<Governance | null>(null);

  const [draftId, setDraftId] = useState("");
  const [channel, setChannel] = useState<(typeof CHANNELS)[number]>("telegram");
  const [chatId, setChatId] = useState("");
  const [campaignCode, setCampaignCode] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [landingUrl, setLandingUrl] = useState("");
  const [imageTemplate, setImageTemplate] = useState("");
  const [imageSize, setImageSize] = useState<(typeof IMAGE_SIZES)[number]>("square");

  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<JobCreated | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDrafts = useCallback(async () => {
    // The drafts endpoint takes a single status per query — fetch both
    // publishable statuses and merge, newest first.
    const [approvedResp, editedResp] = await Promise.all([
      api("/content/drafts?status=approved"),
      api("/content/drafts?status=edited"),
    ]);
    if (approvedResp.status === 401 || editedResp.status === 401) {
      router.push("/login");
      return;
    }
    const approved = approvedResp.ok ? (await approvedResp.json()).drafts : [];
    const edited = editedResp.ok ? (await editedResp.json()).drafts : [];
    const merged: Draft[] = [...approved, ...edited].sort((a, b) =>
      a.created_at < b.created_at ? 1 : -1
    );
    setDrafts(merged);
  }, [router]);

  const loadJobs = useCallback(async () => {
    const resp = await api("/publish/jobs");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    if (!resp.ok) {
      setJobs([]);
      return;
    }
    setJobs((await resp.json()).jobs);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    loadDrafts().catch(() => setDrafts([]));
    loadJobs().catch(() => setJobs([]));
    api("/governance/status")
      .then(async (resp) => {
        if (resp.ok) setGovernance(await resp.json());
      })
      .catch(() => {});
  }, [router, loadDrafts, loadJobs]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const payload: Record<string, unknown> = {
        draft_id: draftId,
        channel,
        chat_id: chatId,
        campaign_code: campaignCode,
      };
      if (scheduledAt) payload.scheduled_at = new Date(scheduledAt).toISOString();
      if (landingUrl.trim()) payload.landing_url = landingUrl.trim();
      if (imageTemplate) payload.image = { template: imageTemplate, size: imageSize };

      const resp = await api("/publish/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        const detail = await readErrorDetail(resp);
        setError(
          detail
            ? `${fa.publish.error} ${fa.publish.error_detail_prefix}${detail}`
            : fa.publish.error
        );
        return;
      }
      setCreated(await resp.json());
      setCampaignCode("");
      setScheduledAt("");
      await loadJobs();
    } catch {
      setError(fa.publish.error);
    } finally {
      setBusy(false);
    }
  }

  if (drafts === null || jobs === null) {
    return (
      <main>
        <p className="muted">{fa.publish.loading}</p>
      </main>
    );
  }

  const halted = governance !== null && (governance.silence || governance.kill);

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{fa.publish.title}</h1>
          <p>{fa.publish.subtitle}</p>
        </div>
      </header>

      {halted && (
        <div className="queue" style={{ marginBottom: 22 }}>
          <section className="card blocked" role="alert">
            {fa.publish.halted_banner}
          </section>
        </div>
      )}

      <div className="qhead">
        <h2>{fa.publish.form_heading}</h2>
        <span className="rule" aria-hidden="true" />
      </div>

      <section className="card">
        {drafts.length === 0 ? (
          <p className="muted">{fa.publish.draft_empty}</p>
        ) : (
          <form onSubmit={submit}>
            <label>
              {fa.publish.draft}
              <select required value={draftId} onChange={(e) => setDraftId(e.target.value)}>
                <option value="" disabled>
                  {fa.publish.draft_placeholder}
                </option>
                {drafts.map((d) => (
                  <option key={d.draft_id} value={d.draft_id}>
                    {draftLabel(d)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {fa.publish.channel}
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value as (typeof CHANNELS)[number])}
              >
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>
                    {fa.publish.channels[c]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {fa.publish.chat_id}
              <input
                type="text"
                required
                dir="ltr"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
              />
            </label>
            <label>
              {fa.publish.campaign_code}
              <input
                type="text"
                required
                dir="ltr"
                value={campaignCode}
                onChange={(e) => setCampaignCode(e.target.value)}
              />
            </label>
            <label>
              {fa.publish.scheduled_at}
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
              />
            </label>
            <label>
              {fa.publish.landing_url}
              <input
                type="url"
                dir="ltr"
                placeholder="https://"
                value={landingUrl}
                onChange={(e) => setLandingUrl(e.target.value)}
              />
            </label>
            <label>
              {fa.publish.image_template}
              <select value={imageTemplate} onChange={(e) => setImageTemplate(e.target.value)}>
                <option value="">{fa.publish.image_none}</option>
                {IMAGE_TEMPLATES.map((t) => (
                  <option key={t} value={t}>
                    {fa.publish.image_templates[t]}
                  </option>
                ))}
              </select>
            </label>
            {imageTemplate && (
              <label>
                {fa.publish.image_size}
                <select
                  value={imageSize}
                  onChange={(e) => setImageSize(e.target.value as (typeof IMAGE_SIZES)[number])}
                >
                  {IMAGE_SIZES.map((s) => (
                    <option key={s} value={s}>
                      {fa.publish.image_sizes[s]}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {error && <p role="alert">{error}</p>}
            {created && (
              <p role="status">
                {fa.publish.created} {fa.publish.job_id}
                {created.job_id} · {fa.publish.status}
                {statusLabel(created.status)} ·{" "}
                <span dir="ltr">
                  {fa.publish.utm}
                  {formatUtm(created.utm)}
                </span>
              </p>
            )}

            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? fa.publish.busy : fa.publish.submit}
            </button>
          </form>
        )}
      </section>

      <div className="qhead" style={{ marginTop: 26 }}>
        <h2>{fa.publish.jobs_heading}</h2>
        <span className="rule" aria-hidden="true" />
        <button className="btn" type="button" onClick={() => loadJobs().catch(() => {})}>
          {fa.publish.refresh}
        </button>
      </div>

      {jobs.length === 0 ? (
        <section className="empty-state">
          <p>{fa.publish.empty}</p>
        </section>
      ) : (
        <div className="queue">
          {jobs.map((job) => (
            <section
              key={job.job_id}
              className={`card ${job.status === "sent" ? "ready" : "warned"}`}
            >
              <div className="meta">
                <span className={`chip ${job.status === "sent" ? "ok" : "warn"}`}>
                  {statusLabel(job.status)}
                </span>
                <span className="chip plain">{channelLabel(job.channel)}</span>
                <span className="chip plain" dir="ltr">
                  {job.campaign_code}
                </span>
                <span>
                  {fa.publish.attempts}
                  {faNum(job.attempts)}
                </span>
              </div>
              <p className="text">
                {job.scheduled_at &&
                  `${fa.publish.scheduled_label}${faDateTime(job.scheduled_at)} · `}
                {job.sent_at
                  ? `${fa.publish.sent_label}${relativeTime(job.sent_at)}`
                  : `${fa.publish.created_label}${relativeTime(job.created_at)}`}
              </p>
              {job.landing_url && (
                <a href={job.landing_url} target="_blank" rel="noreferrer">
                  {fa.publish.landing_link}
                </a>
              )}
            </section>
          ))}
        </div>
      )}
    </main>
  );
}

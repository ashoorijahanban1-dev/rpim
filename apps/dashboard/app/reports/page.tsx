"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";
import { APP_TIMEZONE, faNum } from "@/lib/format";

type Report = {
  month: string;
  drafts: { created: number; approved: number; edited: number; rejected: number };
  publish: { queued: number; sent: number; by_channel: Record<string, number> };
  campaigns: { campaign_code: string; jobs: number; sent: number; clicks: number }[];
  clicks: { total: number; by_campaign: Record<string, number> };
  costs: { total_usd: number; by_provider: Record<string, number> };
};

type TrendBucket = {
  month: string;
  drafts_created: number;
  drafts_approved: number;
  sent: number;
  clicks: number;
};

type GovFlags = { silence: boolean; kill: boolean };

function currentMonth(): string {
  // YYYY-MM in the app timezone (ADR 0032) — en-CA gives ISO-style parts.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: APP_TIMEZONE,
    year: "numeric",
    month: "2-digit",
  })
    .format(new Date())
    .slice(0, 7);
}

function channelLabel(channel: string): string {
  const map = fa.publish.channels as Record<string, string>;
  return map[channel] ?? channel;
}

/* Single-measure horizontal bars: identity lives in the row label, magnitude
   in length — one validated hue (--chart-mark), values in text tokens.
   (dataviz spec: thin marks, rounded data-end, direct labels, no legend for
   a single series.) */
function HBarChart({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: number }[];
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div>
        {rows.map((r) => (
          <div className="hbar-row" key={r.label}>
            <span className="hbar-label" dir="auto">
              {r.label}
            </span>
            <span className="hbar-track">
              <span
                className="hbar-fill"
                style={{ inlineSize: `${Math.round((r.value / max) * 100)}%` }}
                title={`${r.label}: ${faNum(r.value)}`}
              />
            </span>
            <span className="hbar-value">{faNum(r.value)}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

export default function ReportsPage() {
  const router = useRouter();
  const [month, setMonth] = useState(currentMonth());
  const [report, setReport] = useState<Report | null>(null);
  const [trend, setTrend] = useState<TrendBucket[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [flags, setFlags] = useState<GovFlags | null>(null);
  const [silenceReason, setSilenceReason] = useState("");
  const [silenceBusy, setSilenceBusy] = useState(false);
  const [silenceError, setSilenceError] = useState<string | null>(null);

  const load = useCallback(
    async (m: string) => {
      setBusy(true);
      try {
        const resp = await api(`/reports/monthly?month=${encodeURIComponent(m)}`);
        if (resp.status === 401) {
          router.push("/login");
          return;
        }
        if (resp.ok) setReport(await resp.json());
      } finally {
        setBusy(false);
      }
    },
    [router],
  );

  const loadFlags = useCallback(async () => {
    const resp = await api("/governance/status");
    if (resp.ok) setFlags(await resp.json());
  }, []);

  const loadTrend = useCallback(async () => {
    const resp = await api("/reports/trend?months=6");
    if (resp.ok) setTrend((await resp.json()).months);
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load(currentMonth()).catch(() => setReport(null));
    loadFlags().catch(() => setFlags(null));
    loadTrend().catch(() => setTrend(null));
  }, [router, load, loadFlags, loadTrend]);

  async function toggleSilence() {
    if (!flags) return;
    if (!silenceReason.trim()) {
      setSilenceError(fa.reports.silence_reason_required);
      return;
    }
    setSilenceBusy(true);
    setSilenceError(null);
    try {
      const resp = await api("/governance/silence", {
        method: "POST",
        body: JSON.stringify({ active: !flags.silence, reason: silenceReason.trim() }),
      });
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        setSilenceError(fa.reports.silence_error);
        return;
      }
      setSilenceReason("");
      await loadFlags();
    } catch {
      setSilenceError(fa.reports.silence_error);
    } finally {
      setSilenceBusy(false);
    }
  }

  const hasData =
    report &&
    (report.drafts.created > 0 || report.publish.queued > 0 || report.publish.sent > 0);

  const channelRows = report
    ? Object.entries(report.publish.by_channel).map(([channel, count]) => ({
        label: channelLabel(channel),
        value: count,
      }))
    : [];
  const campaignRows = report
    ? report.campaigns
        .filter((c) => c.clicks > 0)
        .map((c) => ({ label: c.campaign_code, value: c.clicks }))
    : [];
  const trendRows = trend ?? [];
  const trendHasData = trendRows.some(
    (t) => t.drafts_created > 0 || t.sent > 0 || t.clicks > 0,
  );

  function ctrLabel(c: { sent: number; clicks: number }): string {
    if (c.sent === 0) return fa.reports.ctr_none;
    return `${faNum(Math.round((c.clicks / c.sent) * 100))}${fa.reports.percent}`;
  }

  return (
    <main>
      <div className="page-header">
        <h1>{fa.reports.title}</h1>
      </div>

      <section aria-labelledby="silence-heading">
        <h2 id="silence-heading">{fa.reports.silence_heading}</h2>
        <p className="muted">{fa.reports.silence_desc}</p>
        {flags && (
          <p>
            <span className={flags.silence ? "chip warn" : "chip ok"}>
              {flags.silence ? fa.reports.silence_on_chip : fa.reports.silence_off_chip}
            </span>{" "}
            {flags.kill && <span className="chip danger">{fa.reports.kill_chip}</span>}
          </p>
        )}
        <div className="silence-row">
          <input
            type="text"
            value={silenceReason}
            onChange={(e) => setSilenceReason(e.target.value)}
            aria-label={fa.reports.silence_reason}
            placeholder={fa.reports.silence_reason}
          />
          <button
            className={flags?.silence ? "btn primary" : "btn ghost-danger"}
            onClick={toggleSilence}
            disabled={silenceBusy || !flags}
          >
            {silenceBusy
              ? fa.reports.silence_busy
              : flags?.silence
                ? fa.reports.silence_release
                : fa.reports.silence_activate}
          </button>
        </div>
        {silenceError && <p role="alert">{silenceError}</p>}
      </section>

      <section>
        <label>
          {fa.reports.month_label}
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} dir="ltr" />
        </label>
        <button onClick={() => load(month)} disabled={busy}>
          {busy ? fa.reports.loading : fa.reports.load}
        </button>
      </section>

      {report && !hasData && (
        <section>
          <p className="empty-state">{fa.reports.empty}</p>
        </section>
      )}

      {report && hasData && (
        <>
          <div className="stats">
            <div className="stat">
              <div className="k">{fa.reports.tile_created}</div>
              <div className="v">{faNum(report.drafts.created)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_approved}</div>
              <div className="v">{faNum(report.drafts.approved)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_sent}</div>
              <div className="v">{faNum(report.publish.sent)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_clicks}</div>
              <div className="v">{faNum(report.clicks.total)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_edited}</div>
              <div className="v">{faNum(report.drafts.edited)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_rejected}</div>
              <div className="v">{faNum(report.drafts.rejected)}</div>
            </div>
            <div className="stat">
              <div className="k">{fa.reports.tile_queued}</div>
              <div className="v">{faNum(report.publish.queued)}</div>
            </div>
          </div>

          {channelRows.length > 0 && (
            <section>
              <HBarChart title={fa.reports.chart_channels} rows={channelRows} />
            </section>
          )}

          {campaignRows.length > 0 && (
            <section>
              <HBarChart title={fa.reports.chart_campaigns} rows={campaignRows} />
            </section>
          )}

          <section>
            <h2>{fa.reports.campaigns}</h2>
            <table className="report-table" aria-label={fa.reports.campaigns_table_aria}>
              <thead>
                <tr>
                  <th>{fa.reports.campaign_code}</th>
                  <th>{fa.reports.jobs}</th>
                  <th>{fa.reports.sent}</th>
                  <th>{fa.reports.clicks}</th>
                  <th>{fa.reports.ctr}</th>
                </tr>
              </thead>
              <tbody>
                {report.campaigns.map((c) => (
                  <tr key={c.campaign_code}>
                    <td dir="ltr">{c.campaign_code}</td>
                    <td>{faNum(c.jobs)}</td>
                    <td>{faNum(c.sent)}</td>
                    <td>{faNum(c.clicks)}</td>
                    <td>{ctrLabel(c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {trendHasData && (
            <section>
              <h2>{fa.reports.trend_heading}</h2>
              <HBarChart
                title={fa.reports.chart_trend_clicks}
                rows={trendRows.map((t) => ({ label: t.month, value: t.clicks }))}
              />
              <table className="report-table" aria-label={fa.reports.trend_table_aria}>
                <thead>
                  <tr>
                    <th>{fa.reports.month_label}</th>
                    <th>{fa.reports.created}</th>
                    <th>{fa.reports.approved}</th>
                    <th>{fa.reports.sent}</th>
                    <th>{fa.reports.clicks}</th>
                  </tr>
                </thead>
                <tbody>
                  {trendRows.map((t) => (
                    <tr key={t.month}>
                      <td dir="ltr">{t.month}</td>
                      <td>{faNum(t.drafts_created)}</td>
                      <td>{faNum(t.drafts_approved)}</td>
                      <td>{faNum(t.sent)}</td>
                      <td>{faNum(t.clicks)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section>
            <h2>{fa.reports.costs}</h2>
            <div className="stats">
              <div className="stat">
                <div className="k">{fa.reports.tile_cost}</div>
                <div className="v" dir="ltr">
                  {report.costs.total_usd.toFixed(4)}
                </div>
              </div>
            </div>
            <p className="muted">
              {fa.reports.by_provider}:{" "}
              {Object.entries(report.costs.by_provider)
                .map(([provider, cost]) => `${provider}: ${cost.toFixed(4)}`)
                .join(" · ")}
            </p>
          </section>
        </>
      )}
    </main>
  );
}

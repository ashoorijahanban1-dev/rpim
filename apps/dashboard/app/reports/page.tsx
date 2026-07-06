"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";

type Report = {
  month: string;
  drafts: { created: number; approved: number; edited: number; rejected: number };
  publish: { queued: number; sent: number; by_channel: Record<string, number> };
  campaigns: { campaign_code: string; jobs: number; sent: number; clicks: number }[];
  clicks: { total: number; by_campaign: Record<string, number> };
  costs: { total_usd: number; by_provider: Record<string, number> };
};

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export default function ReportsPage() {
  const router = useRouter();
  const [month, setMonth] = useState(currentMonth());
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);

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

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load(currentMonth()).catch(() => setReport(null));
  }, [router, load]);

  const hasData =
    report &&
    (report.drafts.created > 0 || report.publish.queued > 0 || report.publish.sent > 0);

  return (
    <main>
      <h1>{fa.reports.title}</h1>
      <p>
        <Link href="/queue">{fa.reports.back_queue}</Link>
      </p>
      <label>
        {fa.reports.month_label}
        <input
          type="text"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          dir="ltr"
        />
      </label>
      <button onClick={() => load(month)} disabled={busy}>
        {busy ? fa.reports.loading : fa.reports.load}
      </button>

      {report && !hasData && <p>{fa.reports.empty}</p>}
      {report && hasData && (
        <>
          <section>
            <h2>{fa.reports.drafts}</h2>
            <p>
              {fa.reports.created}: {report.drafts.created} · {fa.reports.approved}:{" "}
              {report.drafts.approved} · {fa.reports.edited}: {report.drafts.edited} ·{" "}
              {fa.reports.rejected}: {report.drafts.rejected}
            </p>
          </section>
          <section>
            <h2>{fa.reports.publish}</h2>
            <p>
              {fa.reports.queued}: {report.publish.queued} · {fa.reports.sent}:{" "}
              {report.publish.sent}
            </p>
            <p>
              {fa.reports.by_channel}:{" "}
              {Object.entries(report.publish.by_channel)
                .map(([channel, count]) => `${channel}: ${count}`)
                .join(" · ")}
            </p>
          </section>
          <section>
            <h2>{fa.reports.campaigns}</h2>
            {report.campaigns.map((c) => (
              <p key={c.campaign_code} dir="auto">
                {fa.reports.campaign_code}: {c.campaign_code} — {fa.reports.jobs}: {c.jobs} ·{" "}
                {fa.reports.sent}: {c.sent} · {fa.reports.clicks}: {c.clicks}
              </p>
            ))}
            <p>
              {fa.reports.clicks_total}: {report.clicks.total}
            </p>
          </section>
          <section>
            <h2>{fa.reports.costs}</h2>
            <p>
              {fa.reports.total_cost}: {report.costs.total_usd}
            </p>
            <p>
              {fa.reports.by_provider}:{" "}
              {Object.entries(report.costs.by_provider)
                .map(([provider, cost]) => `${provider}: ${cost}`)
                .join(" · ")}
            </p>
          </section>
        </>
      )}
    </main>
  );
}

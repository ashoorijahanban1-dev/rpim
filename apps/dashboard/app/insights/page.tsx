"use client";

// Tenant insights (M22 slice E, ADR 0045): summary cards + campaign table
// off GET /metrics/summary, and the learnings list off GET /learnings with
// the owner-only retire control behind an explicit in-UI confirm step.
// The window shown here is EXACTLY what the distiller learns from.
// ADR 0040: framer-motion stagger, honoring prefers-reduced-motion.

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, MotionConfig, type Variants } from "framer-motion";
import fa from "@/locales/fa.json";
import { api, getToken, readErrorDetail } from "@/lib/api";
import { faNum, relativeTime } from "@/lib/format";

type CampaignRow = {
  campaign: string;
  clicks: number;
  posts_sent: number;
  ctr: number | null;
};

type Summary = {
  window_days: number;
  campaigns: CampaignRow[];
  rejects: Record<string, number>;
};

type Directive = { key: string; text_fa: string; weight: number };

type Learning = {
  version: number;
  directives: Directive[];
  evidence: Record<string, unknown>;
  status: string;
  created_at: string;
};

const staggered: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.08 } },
};

const fadeUp: Variants = {
  initial: { opacity: 0, y: 20 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] },
  },
};

export default function InsightsPage() {
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [learnings, setLearnings] = useState<Learning[] | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const [retired, setRetired] = useState(false);

  const load = useCallback(async () => {
    const resp = await api("/metrics/summary");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    if (!resp.ok) {
      setError(fa.insights.error);
      return;
    }
    setSummary(await resp.json());
    const learningsResp = await api("/learnings");
    if (learningsResp.ok) setLearnings((await learningsResp.json()).items);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setError(fa.insights.error));
  }, [router, load]);

  async function retire(version: number) {
    // Human approval in the UI (two-step confirm); the API is owner-only.
    if (confirming !== version) {
      setConfirming(version);
      return;
    }
    setConfirming(null);
    const resp = await api(`/learnings/${version}/retire`, { method: "POST" });
    if (!resp.ok) {
      setError((await readErrorDetail(resp)) || fa.insights.error);
      return;
    }
    setRetired(true);
    await load();
  }

  const loading = !summary && !error;
  const totalClicks = summary?.campaigns.reduce((sum, c) => sum + c.clicks, 0) ?? 0;
  const totalRejects = Object.values(summary?.rejects ?? {}).reduce(
    (sum, n) => sum + n,
    0,
  );

  return (
    <MotionConfig reducedMotion="user">
      <motion.main variants={staggered} initial="initial" animate="animate">
        <motion.div variants={fadeUp} className="page-header">
          <h1>{fa.insights.title}</h1>
        </motion.div>
        <motion.p variants={fadeUp} className="muted">
          {fa.insights.hint}
        </motion.p>

        {loading && <p role="status">{fa.insights.loading}</p>}
        {error && (
          <p className="empty-state" role="alert">
            {error}
          </p>
        )}
        {retired && <p role="status">{fa.insights.retire_done}</p>}

        {summary && (
          <motion.section variants={fadeUp}>
            <div className="stats">
              <div className="stat">
                <span className="k">{fa.insights.card_clicks}</span>
                <span className="v">{faNum(totalClicks)}</span>
              </div>
              <div className="stat">
                <span className="k">{fa.insights.card_campaigns}</span>
                <span className="v">{faNum(summary.campaigns.length)}</span>
              </div>
              <div className="stat">
                <span className="k">{fa.insights.card_rejects}</span>
                <span className="v">{faNum(totalRejects)}</span>
              </div>
            </div>
            <p className="muted">
              {fa.insights.window_hint.replace("{days}", faNum(summary.window_days))}
            </p>

            {summary.campaigns.length === 0 && (
              <p className="empty-state">{fa.insights.empty_metrics}</p>
            )}
            {summary.campaigns.length > 0 && (
              <table
                className="report-table"
                aria-label={fa.insights.metrics_table_aria}
              >
                <thead>
                  <tr>
                    <th>{fa.insights.th_campaign}</th>
                    <th>{fa.insights.th_clicks}</th>
                    <th>{fa.insights.th_posts}</th>
                    <th>{fa.insights.th_ctr}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.campaigns.map((row) => (
                    <tr key={row.campaign}>
                      <td>{row.campaign}</td>
                      <td>{faNum(row.clicks)}</td>
                      <td>{faNum(row.posts_sent)}</td>
                      <td>
                        {row.ctr === null ? fa.insights.no_value : faNum(row.ctr)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </motion.section>
        )}

        {summary && (
          <motion.section variants={fadeUp}>
            <div className="page-header">
              <h2>{fa.insights.learnings_title}</h2>
            </div>
            <p className="muted">{fa.insights.learnings_hint}</p>

            {learnings && learnings.length === 0 && (
              <p className="empty-state">{fa.insights.empty_learnings}</p>
            )}
            {learnings && learnings.length > 0 && (
              <ul className="plain">
                {learnings.map((item) => (
                  <li key={item.version}>
                    <div className="page-header">
                      <h3>
                        {fa.insights.version_label} {faNum(item.version)}{" "}
                        <span
                          className={item.status === "active" ? "chip ok" : "chip"}
                        >
                          {item.status === "active"
                            ? fa.insights.status_active
                            : fa.insights.status_retired}
                        </span>
                      </h3>
                      {item.status === "active" && (
                        <button
                          type="button"
                          aria-label={fa.insights.retire_aria}
                          onClick={() => retire(item.version)}
                        >
                          {confirming === item.version
                            ? fa.insights.retire_confirm
                            : fa.insights.retire}
                        </button>
                      )}
                    </div>
                    <span className="muted">{relativeTime(item.created_at)}</span>
                    <ul className="plain">
                      {item.directives.map((directive) => (
                        <li key={directive.key}>{directive.text_fa}</li>
                      ))}
                    </ul>
                    <details>
                      <summary>{fa.insights.evidence}</summary>
                      <pre dir="ltr">{JSON.stringify(item.evidence, null, 2)}</pre>
                    </details>
                  </li>
                ))}
              </ul>
            )}
          </motion.section>
        )}
      </motion.main>
    </MotionConfig>
  );
}

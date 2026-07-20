"use client";

// Super Admin panel (M18): direct-URL page — deliberately absent from the
// tenant sidebar. Non-admins get the API's 403 and see fa.admin.denied.
// ADR 0040: framer-motion stagger on load, honoring prefers-reduced-motion.

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, MotionConfig, type Variants } from "framer-motion";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";
import { faNum, relativeTime } from "@/lib/format";

type AdminChannel = {
  channel: string;
  status: string;
  secret_set: boolean;
};

type AdminTenant = {
  tenant_id: string;
  name: string;
  created_at: string | null;
  users: number;
  channels: AdminChannel[];
  costs: { total_usd: number; tokens: number };
};

type AiNewsItem = {
  title: string;
  url: string;
  source: string;
  fetched_at: string | null;
};

const CHANNEL_LABELS: Record<string, string> = fa.publish.channels;

// Smooth stagger: sections fade-and-rise in sequence (150-300ms band,
// decelerating ease — the Pro motion scale from globals.css / ADR 0040).
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

export default function AdminPage() {
  const router = useRouter();
  const [tenants, setTenants] = useState<AdminTenant[] | null>(null);
  const [news, setNews] = useState<AiNewsItem[] | null>(null);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    const resp = await api("/admin/tenants");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    if (resp.status === 403) {
      setDenied(true);
      return;
    }
    if (!resp.ok) {
      setError(true);
      return;
    }
    setTenants((await resp.json()).tenants);
    const newsResp = await api("/admin/ai-news");
    if (newsResp.ok) setNews((await newsResp.json()).items);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setError(true));
  }, [router, load]);

  return (
    <MotionConfig reducedMotion="user">
      <motion.main variants={staggered} initial="initial" animate="animate">
        <motion.div variants={fadeUp} className="page-header">
          <h1>{fa.admin.title}</h1>
        </motion.div>
        <motion.p variants={fadeUp} className="muted">
          {fa.admin.hint}
        </motion.p>

        {denied && <p className="empty-state">{fa.admin.denied}</p>}
        {error && <p className="empty-state">{fa.admin.error}</p>}

        {tenants && tenants.length === 0 && (
          <p className="empty-state">{fa.admin.empty}</p>
        )}

        {tenants && tenants.length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          >
            <table className="report-table" aria-label={fa.admin.table_aria}>
              <thead>
                <tr>
                  <th>{fa.admin.tenants}</th>
                  <th>{fa.admin.users}</th>
                  <th>{fa.admin.cost}</th>
                  <th>{fa.admin.tokens}</th>
                  <th>{fa.admin.channels}</th>
                  <th>{fa.admin.created_at}</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr key={tenant.tenant_id}>
                    <td>{tenant.name}</td>
                    <td>{faNum(tenant.users)}</td>
                    <td>{faNum(tenant.costs.total_usd)}</td>
                    <td>{faNum(tenant.costs.tokens)}</td>
                    <td>
                      {tenant.channels.map((ch) => (
                        <span
                          key={ch.channel}
                          className={ch.status === "connected" ? "chip ok" : "chip"}
                          title={
                            ch.status === "connected"
                              ? fa.admin.connected
                              : fa.admin.disconnected
                          }
                        >
                          {CHANNEL_LABELS[ch.channel] ?? ch.channel}
                        </span>
                      ))}
                    </td>
                    <td>
                      {tenant.created_at
                        ? relativeTime(tenant.created_at)
                        : fa.admin.no_date}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </motion.section>
        )}

        {!denied && !error && (
          <motion.section variants={fadeUp}>
            <div className="page-header">
              <h2>{fa.admin.suggestions_title}</h2>
            </div>
            <p className="muted">{fa.admin.suggestions_hint}</p>
            {news && news.length === 0 && (
              <p className="empty-state">{fa.admin.suggestions_empty}</p>
            )}
            {news && news.length > 0 && (
              <ul className="plain">
                {news.map((item) => (
                  <li key={item.url}>
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.title}
                    </a>{" "}
                    <span className="muted">
                      {fa.admin.suggestions_source}: {item.source}
                      {item.fetched_at ? ` · ${relativeTime(item.fetched_at)}` : ""}
                    </span>
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

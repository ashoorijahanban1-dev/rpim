"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";
import { faNum, relativeTime } from "@/lib/format";

type TrendItem = {
  keyword: string;
  source: string;
  score: number;
  captured_at: string | null;
};

export default function TrendsPage() {
  const router = useRouter();
  const [items, setItems] = useState<TrendItem[] | null>(null);

  const load = useCallback(async () => {
    const resp = await api("/trends");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    if (resp.ok) setItems((await resp.json()).items);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setItems(null));
  }, [router, load]);

  return (
    <main>
      <div className="page-header">
        <h1>{fa.trends.title}</h1>
      </div>
      <p className="muted">{fa.trends.refresh_hint}</p>

      {items && items.length === 0 && (
        <section>
          <p className="empty-state">{fa.trends.empty}</p>
        </section>
      )}

      {items && items.length > 0 && (
        <section>
          <table className="report-table" aria-label={fa.trends.table_aria}>
            <thead>
              <tr>
                <th>{fa.trends.keyword}</th>
                <th>{fa.trends.score}</th>
                <th>{fa.trends.captured_at}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.source}:${item.keyword}`}>
                  <td dir="auto">{item.keyword}</td>
                  <td>
                    <span className="hbar-track" style={{ inlineSize: "8rem" }}>
                      <span
                        className="hbar-fill"
                        style={{ inlineSize: `${item.score}%` }}
                        title={faNum(item.score)}
                      />
                    </span>{" "}
                    {faNum(item.score)}
                  </td>
                  <td>{item.captured_at ? relativeTime(item.captured_at) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}

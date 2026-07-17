"use client";

// Super Admin panel (M18): direct-URL page — deliberately absent from the
// tenant sidebar. Non-admins get the API's 403 and see fa.admin.denied.

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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

const CHANNEL_LABELS: Record<string, string> = fa.publish.channels;

export default function AdminPage() {
  const router = useRouter();
  const [tenants, setTenants] = useState<AdminTenant[] | null>(null);
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
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setError(true));
  }, [router, load]);

  return (
    <main>
      <div className="page-header">
        <h1>{fa.admin.title}</h1>
      </div>
      <p className="muted">{fa.admin.hint}</p>

      {denied && <p className="empty-state">{fa.admin.denied}</p>}
      {error && <p className="empty-state">{fa.admin.error}</p>}

      {tenants && tenants.length === 0 && (
        <p className="empty-state">{fa.admin.empty}</p>
      )}

      {tenants && tenants.length > 0 && (
        <section>
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
        </section>
      )}
    </main>
  );
}

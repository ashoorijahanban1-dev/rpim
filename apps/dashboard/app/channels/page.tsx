"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";

type Connection = {
  channel: string;
  status: string;
  secret_set: boolean;
  config: Record<string, string>;
};

function channelLabel(channel: string): string {
  const map = fa.publish.channels as Record<string, string>;
  return map[channel] ?? channel;
}

function ChannelCard({
  connection,
  onSaved,
}: {
  connection: Connection;
  onSaved: () => Promise<void>;
}) {
  const [secret, setSecret] = useState("");
  const [chatId, setChatId] = useState(connection.config.chat_id ?? "");
  const [baseUrl, setBaseUrl] = useState(connection.config.base_url ?? "");
  const [user, setUser] = useState(connection.config.user ?? "");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const isWordpress = connection.channel === "wordpress";

  async function save() {
    setBusy(true);
    setNotice(null);
    try {
      const config = isWordpress ? { base_url: baseUrl, user } : { chat_id: chatId };
      const resp = await api(`/channels/${connection.channel}`, {
        method: "PUT",
        body: JSON.stringify({ secret: secret || null, config }),
      });
      setNotice(resp.ok ? fa.channels_hub.saved : fa.channels_hub.error);
      if (resp.ok) {
        setSecret("");
        await onSaved();
      }
    } catch {
      setNotice(fa.channels_hub.error);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setNotice(null);
    try {
      const resp = await api(`/channels/${connection.channel}`, { method: "DELETE" });
      setNotice(resp.ok ? fa.channels_hub.saved : fa.channels_hub.error);
      if (resp.ok) await onSaved();
    } catch {
      setNotice(fa.channels_hub.error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="chart">
      <h2>
        {channelLabel(connection.channel)}{" "}
        <span className={connection.status === "connected" ? "chip ok" : "chip warn"}>
          {connection.status === "connected"
            ? fa.channels_hub.connected
            : fa.channels_hub.disconnected}
        </span>
      </h2>
      <label>
        {fa.channels_hub.secret_label}
        <input
          type="password"
          dir="ltr"
          value={secret}
          placeholder={connection.secret_set ? "••••••••" : ""}
          onChange={(e) => setSecret(e.target.value)}
        />
      </label>
      {connection.secret_set && <p className="muted">{fa.channels_hub.secret_keep_hint}</p>}
      {isWordpress ? (
        <>
          <label>
            {fa.channels_hub.config_base_url}
            <input dir="ltr" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </label>
          <label>
            {fa.channels_hub.config_user}
            <input dir="ltr" value={user} onChange={(e) => setUser(e.target.value)} />
          </label>
        </>
      ) : (
        <label>
          {fa.channels_hub.config_chat_id}
          <input dir="ltr" value={chatId} onChange={(e) => setChatId(e.target.value)} />
        </label>
      )}
      {notice && <p role="status">{notice}</p>}
      <button type="button" onClick={save} disabled={busy}>
        {fa.channels_hub.save}
      </button>{" "}
      {connection.secret_set && (
        <button type="button" className="btn ghost-danger" onClick={disconnect} disabled={busy}>
          {fa.channels_hub.disconnect}
        </button>
      )}
    </article>
  );
}

export default function ChannelsPage() {
  const router = useRouter();
  const [channels, setChannels] = useState<Connection[] | null>(null);

  const load = useCallback(async () => {
    const resp = await api("/channels");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    if (resp.ok) setChannels((await resp.json()).channels);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setChannels(null));
  }, [router, load]);

  return (
    <main>
      <div className="page-header">
        <h1>{fa.channels_hub.title}</h1>
      </div>
      <p className="muted">{fa.channels_hub.hint}</p>
      {channels?.map((connection) => (
        <ChannelCard key={connection.channel} connection={connection} onSaved={load} />
      ))}
    </main>
  );
}

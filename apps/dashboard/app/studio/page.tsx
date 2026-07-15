"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type StudioPrompt = {
  prompt_id: string;
  kind: string;
  prompt_text: string;
  created_at: string | null;
};

export default function StudioPage() {
  const router = useRouter();
  const [items, setItems] = useState<StudioPrompt[] | null>(null);
  const [subject, setSubject] = useState("");
  const [mood, setMood] = useState("");
  const [channel, setChannel] = useState("");
  const [kind, setKind] = useState<"image" | "video">("image");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const resp = await api("/studio/prompts");
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await api("/studio/prompts", {
        method: "POST",
        body: JSON.stringify({
          kind,
          brief: { subject, mood: mood || null, channel: channel || null },
        }),
      });
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        setError(fa.studio.error);
        return;
      }
      setSubject("");
      await load();
    } catch {
      setError(fa.studio.error);
    } finally {
      setBusy(false);
    }
  }

  async function copyPrompt(item: StudioPrompt) {
    await navigator.clipboard.writeText(item.prompt_text);
    setCopiedId(item.prompt_id);
    setTimeout(() => setCopiedId(null), 1500);
  }

  return (
    <main>
      <div className="page-header">
        <h1>{fa.studio.title}</h1>
      </div>
      <p className="muted">{fa.studio.hint}</p>

      <form onSubmit={submit}>
        <label>
          {fa.studio.subject}
          <input
            type="text"
            required
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
        </label>
        <label>
          {fa.studio.mood}
          <input type="text" value={mood} onChange={(e) => setMood(e.target.value)} />
        </label>
        <label>
          {fa.studio.channel}
          <input
            type="text"
            dir="ltr"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          />
        </label>
        <label>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "image" | "video")}
            aria-label={`${fa.studio.kind_image}/${fa.studio.kind_video}`}
          >
            <option value="image">{fa.studio.kind_image}</option>
            <option value="video">{fa.studio.kind_video}</option>
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy}>
          {fa.studio.submit}
        </button>
      </form>

      {items && items.length === 0 && (
        <section>
          <p className="empty-state">{fa.studio.empty}</p>
        </section>
      )}

      {items && items.length > 0 && (
        <section aria-label={fa.studio.list_aria}>
          {items.map((item) => (
            <article className="chart" key={item.prompt_id}>
              <p className="muted">
                {item.kind === "video" ? fa.studio.kind_video : fa.studio.kind_image}
                {" · "}
                {item.created_at ? relativeTime(item.created_at) : ""}
              </p>
              <pre dir="ltr" style={{ whiteSpace: "pre-wrap" }}>
                {item.prompt_text}
              </pre>
              <button type="button" onClick={() => copyPrompt(item)}>
                {copiedId === item.prompt_id ? fa.studio.copied : fa.studio.copy}
              </button>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}

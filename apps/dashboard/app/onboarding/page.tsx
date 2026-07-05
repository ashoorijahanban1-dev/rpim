"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, clearToken, getToken } from "@/lib/api";

type Question = {
  id: string;
  field: string;
  kind: "text" | "list" | "pairs";
  question: string;
  hint: string;
};

type Answers = Record<string, string | string[] | Record<string, string>>;

// UI keeps every answer as plain textarea text; conversion to the API shape
// (list = one item per line, pairs = "term: description" per line) is local.
function toApi(kind: Question["kind"], raw: string) {
  if (kind === "text") return raw.trim();
  const lines = raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  if (kind === "list") return lines;
  const pairs: Record<string, string> = {};
  for (const line of lines) {
    const idx = line.indexOf(":");
    if (idx > 0) pairs[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return pairs;
}

function fromApi(kind: Question["kind"], value: Answers[string] | undefined): string {
  if (value == null) return "";
  if (kind === "text") return String(value);
  if (kind === "list" && Array.isArray(value)) return value.join("\n");
  if (kind === "pairs" && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value)
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n");
  }
  return "";
}

export default function OnboardingPage() {
  const router = useRouter();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string>("loading");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const resp = await api("/onboarding/interview");
    if (resp.status === 401) {
      router.push("/login");
      return;
    }
    const body = await resp.json();
    setQuestions(body.questions);
    setStatus(body.status);
    const initial: Record<string, string> = {};
    for (const q of body.questions as Question[]) {
      initial[q.field] = fromApi(q.kind, (body.answers as Answers)[q.field]);
    }
    setDrafts(initial);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    load().catch(() => setNotice(fa.auth.error_generic));
  }, [router, load]);

  function payload(): Answers {
    const answers: Answers = {};
    for (const q of questions) {
      const raw = drafts[q.field] ?? "";
      if (raw.trim() !== "") answers[q.field] = toApi(q.kind, raw);
    }
    return answers;
  }

  async function saveDraft() {
    setNotice(null);
    const resp = await api("/onboarding/interview/answers", {
      method: "PUT",
      body: JSON.stringify({ answers: payload() }),
    });
    setNotice(resp.ok ? fa.onboarding.saved : fa.auth.error_generic);
  }

  async function complete() {
    setNotice(null);
    await api("/onboarding/interview/answers", {
      method: "PUT",
      body: JSON.stringify({ answers: payload() }),
    });
    const resp = await api("/onboarding/interview/complete", { method: "POST" });
    if (resp.ok) {
      setStatus("completed");
      setNotice(fa.onboarding.completed);
      return;
    }
    if (resp.status === 422) {
      // Rule 6: never render raw API text — name the empty fields in Persian.
      const labels = fa.onboarding.fields as Record<string, string>;
      const missing = questions
        .filter((q) => (drafts[q.field] ?? "").trim() === "")
        .map((q) => labels[q.field] ?? q.question);
      setNotice(`${fa.onboarding.missing_prefix}${missing.join("، ")}`);
      return;
    }
    setNotice(fa.auth.error_generic);
  }

  if (status === "loading") return <main>{fa.onboarding.loading}</main>;

  return (
    <main>
      <h1>{fa.onboarding.title}</h1>
      <p>{fa.onboarding.subtitle}</p>
      {questions.map((q) => (
        <section key={q.id}>
          <h2>{q.question}</h2>
          <p>
            {q.hint}{" "}
            {q.kind === "list"
              ? fa.onboarding.list_hint
              : q.kind === "pairs"
                ? fa.onboarding.pairs_hint
                : ""}
          </p>
          <textarea
            rows={q.kind === "text" ? 4 : 5}
            value={drafts[q.field] ?? ""}
            onChange={(e) => setDrafts({ ...drafts, [q.field]: e.target.value })}
          />
        </section>
      ))}
      {notice && <p role="status">{notice}</p>}
      <div>
        <button onClick={saveDraft}>{fa.onboarding.save_draft}</button>
        <button onClick={complete}>{fa.onboarding.complete}</button>
        <button
          onClick={() => {
            clearToken();
            router.push("/login");
          }}
        >
          {fa.onboarding.logout}
        </button>
      </div>
    </main>
  );
}

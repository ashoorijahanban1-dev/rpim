"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import fa from "@/locales/fa.json";
import { api, getToken, readErrorDetail } from "@/lib/api";
import { faNum } from "@/lib/format";

// Response shapes confirmed against core-api routers/brain.py:
// POST /brain/sources & /brain/sources/pdf → {source_id, chunks};
// POST /brain/sources/crawl → {source_id, chunks, pages};
// GET /brain/search → {results: [{text, source_id, source_title, score}]}.
type SearchResult = {
  text: string;
  source_id: string;
  source_title: string;
  score: number;
};

type FormState = {
  busy: boolean;
  ok: string | null;
  error: string | null;
};

const IDLE: FormState = { busy: false, ok: null, error: null };

function ingestOk(sourceId: string, chunks: number, pages?: number): string {
  const template = pages === undefined ? fa.brain.ingest_ok : fa.brain.crawl_ok;
  return template
    .replace("{id}", sourceId)
    .replace("{chunks}", faNum(chunks))
    .replace("{pages}", faNum(pages ?? 0));
}

function snippet(text: string, max = 240): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export default function BrainPage() {
  const router = useRouter();

  // text ingest
  const [textTitle, setTextTitle] = useState("");
  const [textBody, setTextBody] = useState("");
  const [textState, setTextState] = useState<FormState>(IDLE);

  // crawl ingest
  const [crawlUrl, setCrawlUrl] = useState("");
  const [crawlPages, setCrawlPages] = useState("5");
  const [crawlState, setCrawlState] = useState<FormState>(IDLE);

  // pdf ingest
  const [pdfTitle, setPdfTitle] = useState("");
  const pdfFileRef = useRef<HTMLInputElement>(null);
  const [pdfState, setPdfState] = useState<FormState>(IDLE);

  // search
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searchState, setSearchState] = useState<FormState>(IDLE);

  useEffect(() => {
    if (!getToken()) router.push("/login");
  }, [router]);

  async function ingest(
    setState: (s: FormState) => void,
    request: () => Promise<Response>,
    onSuccess?: () => void
  ) {
    setState({ busy: true, ok: null, error: null });
    try {
      const resp = await request();
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        const detail = await readErrorDetail(resp);
        setState({
          busy: false,
          ok: null,
          error: detail
            ? `${fa.brain.error} ${fa.brain.error_detail_prefix}${detail}`
            : fa.brain.error,
        });
        return;
      }
      const body = await resp.json();
      setState({ busy: false, ok: ingestOk(body.source_id, body.chunks, body.pages), error: null });
      onSuccess?.();
    } catch {
      setState({ busy: false, ok: null, error: fa.brain.error });
    }
  }

  function submitText(e: React.FormEvent) {
    e.preventDefault();
    ingest(
      setTextState,
      () =>
        api("/brain/sources", {
          method: "POST",
          body: JSON.stringify({ title: textTitle, kind: "upload", text: textBody }),
        }),
      () => {
        setTextTitle("");
        setTextBody("");
      }
    );
  }

  function submitCrawl(e: React.FormEvent) {
    e.preventDefault();
    const maxPages = Math.min(10, Math.max(1, Number(crawlPages) || 5));
    ingest(setCrawlState, () =>
      api("/brain/sources/crawl", {
        method: "POST",
        body: JSON.stringify({ url: crawlUrl, max_pages: maxPages }),
      })
    );
  }

  function submitPdf(e: React.FormEvent) {
    e.preventDefault();
    const file = pdfFileRef.current?.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("title", pdfTitle);
    ingest(
      setPdfState,
      () => api("/brain/sources/pdf", { method: "POST", body: form }),
      () => {
        setPdfTitle("");
        if (pdfFileRef.current) pdfFileRef.current.value = "";
      }
    );
  }

  async function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearchState({ busy: true, ok: null, error: null });
    try {
      const resp = await api(`/brain/search?q=${encodeURIComponent(query)}&k=5`);
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        setSearchState({ busy: false, ok: null, error: fa.brain.search_error });
        return;
      }
      const body = await resp.json();
      setResults(body.results);
      setSearchState(IDLE);
    } catch {
      setSearchState({ busy: false, ok: null, error: fa.brain.search_error });
    }
  }

  function formStatus(state: FormState) {
    return (
      <>
        {state.error && <p role="alert">{state.error}</p>}
        {state.ok && <p role="status">{state.ok}</p>}
      </>
    );
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{fa.brain.title}</h1>
          <p>{fa.brain.subtitle}</p>
        </div>
      </header>

      <div className="qhead">
        <h2>{fa.brain.ingest_heading}</h2>
        <span className="rule" aria-hidden="true" />
      </div>

      <div className="queue">
        <section className="card">
          <h2>{fa.brain.text_heading}</h2>
          <form onSubmit={submitText}>
            <label>
              {fa.brain.text_title}
              <input
                type="text"
                required
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
              />
            </label>
            <label>
              {fa.brain.text_body}
              <textarea
                required
                rows={5}
                value={textBody}
                onChange={(e) => setTextBody(e.target.value)}
              />
            </label>
            {formStatus(textState)}
            <button className="btn primary" type="submit" disabled={textState.busy}>
              {textState.busy ? fa.brain.busy : fa.brain.text_submit}
            </button>
          </form>
        </section>

        <section className="card">
          <h2>{fa.brain.crawl_heading}</h2>
          <form onSubmit={submitCrawl}>
            <label>
              {fa.brain.crawl_url}
              <input
                type="url"
                required
                dir="ltr"
                placeholder="https://"
                value={crawlUrl}
                onChange={(e) => setCrawlUrl(e.target.value)}
              />
            </label>
            <label>
              {fa.brain.crawl_max_pages}
              <input
                type="number"
                min={1}
                max={10}
                value={crawlPages}
                onChange={(e) => setCrawlPages(e.target.value)}
              />
            </label>
            {formStatus(crawlState)}
            <button className="btn primary" type="submit" disabled={crawlState.busy}>
              {crawlState.busy ? fa.brain.busy : fa.brain.crawl_submit}
            </button>
          </form>
        </section>

        <section className="card">
          <h2>{fa.brain.pdf_heading}</h2>
          <form onSubmit={submitPdf}>
            <label>
              {fa.brain.pdf_title}
              <input
                type="text"
                required
                value={pdfTitle}
                onChange={(e) => setPdfTitle(e.target.value)}
              />
            </label>
            <label>
              {fa.brain.pdf_file}
              <input type="file" required accept="application/pdf,.pdf" ref={pdfFileRef} />
            </label>
            {formStatus(pdfState)}
            <button className="btn primary" type="submit" disabled={pdfState.busy}>
              {pdfState.busy ? fa.brain.busy : fa.brain.pdf_submit}
            </button>
          </form>
        </section>
      </div>

      <div className="qhead" style={{ marginTop: 26 }}>
        <h2>{fa.brain.search_heading}</h2>
        <span className="rule" aria-hidden="true" />
      </div>

      <section className="card">
        <form onSubmit={submitSearch}>
          <label>
            {fa.brain.search_heading}
            <input
              type="search"
              required
              placeholder={fa.brain.search_placeholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {searchState.error && <p role="alert">{searchState.error}</p>}
          <button className="btn primary" type="submit" disabled={searchState.busy}>
            {searchState.busy ? fa.brain.searching : fa.brain.search_submit}
          </button>
        </form>
      </section>

      {results !== null && (
        <>
          <div className="qhead" style={{ marginTop: 26 }}>
            <h2>{fa.brain.results_heading}</h2>
            <span className="rule" aria-hidden="true" />
          </div>
          {results.length === 0 ? (
            <section className="empty-state">
              <p>{fa.brain.search_empty}</p>
            </section>
          ) : (
            <div className="queue">
              {results.map((r, i) => (
                <section key={`${r.source_id}-${i}`} className="card ready">
                  <div className="meta">
                    <span className="chip plain">{r.source_title}</span>
                  </div>
                  <p className="text">{snippet(r.text)}</p>
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}

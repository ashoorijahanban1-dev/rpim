"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import fa from "@/locales/fa.json";
import { api, getToken } from "@/lib/api";

type State = "idle" | "busy" | "done" | "error";

export default function ExportPage() {
  const router = useRouter();
  const [state, setState] = useState<State>("idle");

  async function download() {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    setState("busy");
    try {
      const resp = await api("/export");
      if (resp.status === 401) {
        router.push("/login");
        return;
      }
      if (!resp.ok) {
        setState("error");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "rpim-export.json";
      anchor.click();
      URL.revokeObjectURL(url);
      setState("done");
    } catch {
      setState("error");
    }
  }

  return (
    <main>
      <h1>{fa.export.title}</h1>
      <p>{fa.export.subtitle}</p>
      <p>
        <Link href="/queue">{fa.export.back_queue}</Link>
      </p>
      <button onClick={download} disabled={state === "busy"}>
        {state === "busy" ? fa.export.downloading : fa.export.download}
      </button>
      {state === "done" && <p role="status">{fa.export.done}</p>}
      {state === "error" && <p role="alert">{fa.export.error}</p>}
    </main>
  );
}

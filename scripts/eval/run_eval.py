"""Phase-0: the 50-prompt Persian eval that decides MODEL_T2 (CLAUDE.md).

Runs prompts_fa.jsonl against candidate models THROUGH the model-gateway
provider adapters (rpim_model_gateway.providers — never direct SDK calls),
writes per-model result files, and prints a comparison summary. An optional
LLM judge scores each output 1-5 against the prompt's criteria.

Env var NAMES only — keys/values live on the server (rule 4):
  EVAL_CANDIDATES   comma list of provider:model (required),
                    e.g. "gemini:gemini-2.0-flash,deepseek:deepseek-chat"
  EVAL_JUDGE        provider:model used to auto-score outputs (optional;
                    without it, results ship with an empty score column for
                    human scoring)
  EVAL_PROMPTS      prompts file (default: prompts_fa.jsonl next to this file)
  EVAL_RESULTS_DIR  output directory (default: scripts/eval/results)
  EVAL_LIMIT        run only the first N prompts (dev/smoke)
Provider keys read by the adapters: GEMINI_API_KEY, DEEPSEEK_API_KEY,
ANTHROPIC_API_KEY.

Run on the server:  uv run python scripts/eval/run_eval.py
Then set the winner as MODEL_T2 in the Coolify UI (us leg) and redeploy.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from rpim_model_gateway.providers import PROVIDERS, cost_usd

JUDGE_SYSTEM = (
    "تو داور کیفیت خروجی مدل‌های زبانی برای بازاریابی فارسی هستی. "
    "فقط JSON برگردان: {\"score\": عدد ۱ تا ۵, \"reason\": \"دلیل کوتاه\"}"
)

JUDGE_TEMPLATE = (
    "وظیفهٔ داده‌شده به مدل:\n{prompt}\n\n"
    "معیار ارزیابی: {criteria}\n\n"
    "پاسخ مدل:\n{output}\n\n"
    "با توجه به معیار، انجام دقیق وظیفه و کیفیت فارسی، نمرهٔ ۱ تا ۵ بده."
)


def _parse_target(spec: str) -> tuple[str, str]:
    provider, _, model = spec.strip().partition(":")
    if provider not in PROVIDERS or not model:
        raise SystemExit(
            f"bad candidate {spec!r} — use provider:model with provider in "
            f"{sorted(PROVIDERS)}"
        )
    return provider, model


def _judge(spec: tuple[str, str] | None, item: dict, output: str) -> dict:
    if spec is None:
        return {"score": None, "reason": None}
    provider, model = spec
    prompt = JUDGE_TEMPLATE.format(
        prompt=item["prompt"], criteria=item["criteria"], output=output[:4000]
    )
    try:
        raw = PROVIDERS[provider](model, prompt, system=JUDGE_SYSTEM, max_tokens=200)
        match = re.search(r"\{.*\}", raw["text"], re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        score = data.get("score")
        return {
            "score": int(score) if isinstance(score, (int, float)) else None,
            "reason": data.get("reason"),
        }
    except Exception as exc:  # noqa: BLE001 — judge is best-effort
        return {"score": None, "reason": f"judge failed: {type(exc).__name__}"}


def main() -> int:
    here = Path(__file__).resolve().parent
    candidates = [
        _parse_target(spec)
        for spec in os.environ.get("EVAL_CANDIDATES", "").split(",")
        if spec.strip()
    ]
    if not candidates:
        print("set EVAL_CANDIDATES=provider:model[,provider:model…]", file=sys.stderr)
        return 2

    judge_env = os.environ.get("EVAL_JUDGE", "").strip()
    judge = _parse_target(judge_env) if judge_env else None

    prompts_path = Path(os.environ.get("EVAL_PROMPTS", here / "prompts_fa.jsonl"))
    items = [json.loads(line) for line in prompts_path.read_text("utf-8").splitlines() if line]
    limit = os.environ.get("EVAL_LIMIT")
    if limit:
        items = items[: int(limit)]

    results_dir = Path(os.environ.get("EVAL_RESULTS_DIR", here / "results"))
    results_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    for provider, model in candidates:
        out_path = results_dir / f"{provider}-{model}".replace("/", "_")
        rows: list[dict] = []
        ok = errors = tokens_in = tokens_out = 0
        latency_total = 0.0
        scores: list[int] = []
        error_kinds: dict[str, int] = {}
        for item in items:
            started = time.monotonic()
            try:
                reply = PROVIDERS[provider](
                    model, item["prompt"], system=item.get("system"), max_tokens=1024
                )
                elapsed = time.monotonic() - started
                verdict = _judge(judge, item, reply["text"])
                if verdict["score"] is not None:
                    scores.append(verdict["score"])
                ok += 1
                tokens_in += reply["tokens_in"]
                tokens_out += reply["tokens_out"]
                latency_total += elapsed
                rows.append(
                    {
                        "id": item["id"],
                        "category": item["category"],
                        "ok": True,
                        "latency_s": round(elapsed, 2),
                        "tokens_in": reply["tokens_in"],
                        "tokens_out": reply["tokens_out"],
                        "output": reply["text"],
                        **verdict,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — record and continue
                errors += 1
                # Aggregate a short, key-free error signature so the committed
                # summary is diagnosable without the runner-local row files.
                kind = f"{type(exc).__name__}: {str(exc)[:120]}"
                error_kinds[kind] = error_kinds.get(kind, 0) + 1
                rows.append(
                    {"id": item["id"], "category": item["category"], "ok": False,
                     "error": f"{type(exc).__name__}: {exc}"}
                )
            print(f"[{provider}:{model}] {item['id']} done", file=sys.stderr)

        with open(f"{out_path}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        summary.append(
            {
                "candidate": f"{provider}:{model}",
                "ok": ok,
                "errors": errors,
                "mean_score": round(sum(scores) / len(scores), 2) if scores else None,
                "scored": len(scores),
                "mean_latency_s": round(latency_total / ok, 2) if ok else None,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "est_cost_usd": round(cost_usd(model, tokens_in, tokens_out), 4),
                "top_errors": dict(
                    sorted(error_kinds.items(), key=lambda kv: -kv[1])[:3]
                ),
            }
        )

    (results_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    ranked = sorted(
        summary, key=lambda s: (-(s["mean_score"] or 0), s["est_cost_usd"])
    )
    print(json.dumps(ranked, ensure_ascii=False, indent=2))
    if ranked and ranked[0]["mean_score"] is not None:
        print(
            f"\nleader: {ranked[0]['candidate']} — review results/, then set "
            f"MODEL_T2 in the Coolify UI (us leg) and redeploy.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

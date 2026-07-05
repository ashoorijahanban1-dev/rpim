#!/usr/bin/env bash
# End-to-end M2 acceptance probe (§6.4): register → upload → semantic search
# with source refs, latency < 2s. Runs against a LIVE iran leg (CI smoke after
# `make up-iran`/`make up-us`, or a real server). Uses the pg + gateway path.
set -euo pipefail

BASE="${BASE:-http://localhost:${IRAN_HTTP_PORT:-8001}}"
STAMP="$(date +%s)-$RANDOM"
EMAIL="e2e-${STAMP}@example.com"
MARKER="نشانه-${STAMP} محصول ویژه پاییزی با تخفیف استثنایی"

jget() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

TOKEN=$(curl -fsS "$BASE/api/auth/register" -H 'Content-Type: application/json' \
	-d "{\"email\":\"$EMAIL\",\"password\":\"e2e-pass-$STAMP\",\"tenant_name\":\"E2E $STAMP\"}" |
	jget "['access_token']")
echo "e2e: registered tenant"

PAYLOAD=$(MARKER="$MARKER" python3 <<'PY'
import json
import os

marker = os.environ["MARKER"]
text = "\n\n".join(
    [
        "پاراگراف نخست درباره برند ما و ارزش‌های آن است. کیفیت و صداقت پایه کار ماست.",
        f"{marker}. این جمله باید در جستجوی معنایی پیدا شود.",
        "پاراگراف پایانی درباره خدمات پس از فروش و پشتیبانی مشتریان است.",
    ]
)
print(json.dumps({"title": "سند آزمون سرتاسری", "kind": "upload", "text": text}))
PY
)
CHUNKS=$(curl -fsS "$BASE/api/brain/sources" -H "Authorization: Bearer $TOKEN" \
	-H 'Content-Type: application/json' -d "$PAYLOAD" | jget "['chunks']")
echo "e2e: uploaded source ($CHUNKS chunks, embedded via gateway)"

START=$(python3 -c "import time;print(time.time())")
RESP=$(curl -fsS --get "$BASE/api/brain/search" \
	--data-urlencode "q=$MARKER" --data-urlencode "k=5" \
	-H "Authorization: Bearer $TOKEN")
ELAPSED=$(python3 -c "import time;print(time.time()-$START)")

RESP="$RESP" MARKER="$MARKER" ELAPSED="$ELAPSED" python3 <<'PY'
import json
import os

data = json.loads(os.environ["RESP"])
marker = os.environ["MARKER"]
elapsed = float(os.environ["ELAPSED"])

results = data["results"]
assert results, "no search results"
assert len(results) <= 5, f"expected ≤5 results, got {len(results)}"
top = results[0]
assert marker in top["text"], f"top result lacks the marker: {top['text'][:120]!r}"
assert top.get("source_title"), "missing source reference on top result"
assert all("score" in r and "source_id" in r for r in results), "result shape incomplete"
print(f"e2e: top-hit OK · {len(results)} results · latency {elapsed:.2f}s")
assert elapsed < 2.0, f"search latency {elapsed:.2f}s exceeds the 2s acceptance"
PY

echo "smoke-e2e: GREEN"

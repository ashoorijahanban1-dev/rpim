#!/usr/bin/env bash
# READ-ONLY production diagnosis via the Coolify API — no deploys, no writes.
#
# Dumps, for both leg resources (infra/coolify-uuids.conf): app status, the
# stored env vars (values redacted by default — only an allowlist of known
# non-secret names prints, CLAUDE.md rule 4), and a best-effort log tail. This is the session's remote eyes:
# the sandbox cannot reach the panel, GitHub runners can, and the workflow
# commits the report back to docs/ops/ for the session to read.
#
# Usage: COOLIFY_URL=... COOLIFY_TOKEN=... bash scripts/ops-diagnose.sh
set -euo pipefail

: "${COOLIFY_URL:?set COOLIFY_URL}"
: "${COOLIFY_TOKEN:?set COOLIFY_TOKEN (env only — never in code or chat)}"

# shellcheck disable=SC1091
source infra/coolify-uuids.conf
: "${COOLIFY_IRAN_UUID:?missing in infra/coolify-uuids.conf}"
: "${COOLIFY_US_UUID:?missing in infra/coolify-uuids.conf}"

api() {
	local method="$1" path="$2"
	shift 2
	local out code body
	out=$(curl -sS -X "$method" "$COOLIFY_URL/api/v1$path" \
		-H "Authorization: Bearer $COOLIFY_TOKEN" \
		-H "Content-Type: application/json" \
		-w $'\n%{http_code}' "$@")
	code="${out##*$'\n'}"
	body="${out%$'\n'*}"
	if [ "${code:-0}" -ge 400 ] 2>/dev/null; then
		echo "!! API $method $path -> HTTP $code" >&2
		return 1
	fi
	printf '%s' "$body"
}

dump_app() { # label uuid
	local label="$1" uuid="$2"
	echo
	echo "===== $label ($uuid) ====="

	echo "--- application ---"
	# connect_to_docker_network is PATCH-only (absent from the GET schema);
	# the generated docker_compose is the ground truth for what actually
	# deploys — networks, aliases and container names included. It contains
	# env NAMES and ${VAR:-default} placeholders, never secret values.
	api GET "/applications/$uuid" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in ("name", "status", "git_branch", "git_commit_sha",
          "docker_compose_location", "custom_network_aliases",
          "compose_parsing_version", "last_online_at", "updated_at"):
    if k in d:
        print(f"{k}: {d[k]}")
compose = d.get("docker_compose") or ""
print("--- generated docker_compose (Coolify-parsed, truncated) ---")
print(str(compose)[:10000])
' || echo "(application fetch failed)"

	echo "--- envs (redacted by default; only allowlisted names print values) ---"
	api GET "/applications/$uuid/envs" | python3 -c '
import json, re, sys
data = json.load(sys.stdin)
rows = data if isinstance(data, list) else data.get("data", [])
# Rule 4: values are [redacted] UNLESS the name is on the non-secret
# allowlist (a denylist inevitably misses the next credential-shaped name,
# e.g. ZARINPAL_MERCHANT_ID). Deny terms win even over the allowlist, and
# printed values still get URL userinfo scrubbed (redis://:pass@host…).
allow = re.compile(r"^(APP_ENV|POSTGRES_USER|POSTGRES_DB|MODEL_T\d+)$|_(URL|BIND|PORT|MODE|HOST)$")
deny = re.compile(r"TOKEN|SECRET|PASSWORD|PASSPHRASE|KEY|DSN", re.I)
for e in sorted(rows, key=lambda e: e.get("key", "")):
    k, v = e.get("key", ""), str(e.get("value", ""))
    if allow.search(k) and not deny.search(k):
        v = re.sub(r"://[^/@\s]+@", "://[redacted]@", v)
    else:
        v = "[redacted]"
    # The API returns production AND preview/build variants of each key —
    # label them so conflicting values are attributable. NOTE: this whole
    # program lives inside a bash single-quoted string, so no single quotes.
    flags = [f for f in ("is_preview", "is_build_time") if e.get(f)]
    suffix = ("  # " + ",".join(flags)) if flags else ""
    print(f"{k}={v}{suffix}")
' || echo "(envs fetch failed)"

	echo "--- container logs tail (best-effort) ---"
	api GET "/applications/$uuid/logs?lines=150" | python3 -c '
import json, re, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    text = d.get("logs", raw) if isinstance(d, dict) else raw
except ValueError:
    text = raw
# strip credentials embedded in URLs (postgresql://user:pass@host)
text = re.sub(r"://[^/\s@]+@", "://[redacted]@", text)
print(text[-8000:])
' || echo "(logs endpoint unavailable on this Coolify version)"
}

echo "# ops-diagnose — read-only — Coolify $(api GET /version | head -c 40)"
dump_app "rpim-iran-leg" "$COOLIFY_IRAN_UUID"
dump_app "rpim-us-leg" "$COOLIFY_US_UUID"
echo
echo "# end of report"

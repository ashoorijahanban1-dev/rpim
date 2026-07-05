#!/usr/bin/env bash
# Cross-leg healthcheck (M0 acceptance). Three modes:
#   local        — per-leg liveness from this host (dev machines)
#   crossleg-ci  — genuine two-way container egress via host gateway (CI)
#   wg           — over the real WireGuard tunnel (production servers only;
#                  NOT part of automated M0 acceptance — see docs/decisions/)
set -euo pipefail

MODE="${1:-local}"
RETRIES="${RETRIES:-15}"
SLEEP="${SLEEP:-3}"

check() {
	local name="$1" url="$2" i
	for i in $(seq "$RETRIES"); do
		if curl -fsS --max-time 5 "$url" 2>/dev/null | grep -q '"status":[[:space:]]*"ok"'; then
			echo "OK   $name  ($url)"
			return 0
		fi
		sleep "$SLEEP"
	done
	echo "FAIL $name  ($url)" >&2
	return 1
}

case "$MODE" in
local)
	check "iran leg (caddy→core-api)" "http://localhost:${IRAN_HTTP_PORT:-8001}/health"
	check "us leg (model-gateway)" "http://localhost:${GATEWAY_PORT:-8080}/health"
	;;
crossleg-ci)
	echo "iran→us: curl from inside core-api container ..."
	docker compose -f infra/docker-compose.iran.yml -p rpim-iran exec -T core-api \
		python -c "import urllib.request;assert b'\"status\":\"ok\"' in urllib.request.urlopen('http://host.docker.internal:${GATEWAY_PORT:-8080}/health',timeout=10).read().replace(b' ',b'')"
	echo "OK   iran→us"
	echo "us→iran: curl from inside model-gateway container ..."
	docker compose -f infra/docker-compose.us.yml -p rpim-us exec -T model-gateway \
		python -c "import urllib.request;assert b'\"status\":\"ok\"' in urllib.request.urlopen('http://host.docker.internal:${IRAN_HTTP_PORT:-8001}/health',timeout=10).read().replace(b' ',b'')"
	echo "OK   us→iran"
	;;
wg)
	: "${GATEWAY_URL:?set GATEWAY_URL (e.g. http://10.66.0.2:8080) — env only}"
	: "${CORE_API_URL:?set CORE_API_URL (e.g. http://10.66.0.1:8000) — env only}"
	check "iran→us over WireGuard" "${GATEWAY_URL%/}/health"
	check "us→iran over WireGuard" "${CORE_API_URL%/}/health"
	;;
*)
	echo "usage: $0 [local|crossleg-ci|wg]" >&2
	exit 2
	;;
esac

echo "crossleg-healthcheck ($MODE): GREEN"

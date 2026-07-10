#!/usr/bin/env bash
# Idempotent Coolify provisioning for RPIM.
#
# INTERIM TOPOLOGY (ADR 0007 note): BOTH legs deploy to the US server until
# WireGuard + the Iran-network services (M7 Bale/Eitaa, Zarinpal) exist.
# The Iran server (other projects live there) is NOT touched.
#
# Usage:
#   COOLIFY_URL=https://rpim.ir COOLIFY_TOKEN=... bash scripts/coolify-provision.sh
#
# Token comes ONLY from the environment (CLAUDE.md rule 4). Re-running is
# safe: existing project/apps are reused, env vars are only written on first
# creation, deploys are re-triggered.
set -euo pipefail

: "${COOLIFY_URL:?set COOLIFY_URL (https://... — the panel must have valid TLS)}"
: "${COOLIFY_TOKEN:?set COOLIFY_TOKEN (env only — never in code or chat)}"
REPO_URL="${REPO_URL:-https://github.com/ashoorijahanban1-dev/rpim}"
BRANCH="${BRANCH:-main}"

api() {
	# Prints the response body on stdout; on HTTP >= 400 prints the body to
	# stderr too (Coolify's validation messages live there) and returns 1.
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
		echo "!! $body" >&2
		return 1
	fi
	printf '%s' "$body"
}

jqpy() { python3 -c "import sys,json;$1"; }

echo "→ Coolify $(api GET /version | head -c 40)"

SERVER_UUID=$(api GET /servers | jqpy "d=json.load(sys.stdin);print(d[0]['uuid'])")
echo "→ server: $SERVER_UUID"

PROJECT_UUID=$(api GET /projects | jqpy "
d=json.load(sys.stdin)
m=[p for p in d if p.get('name')=='rpim']
print(m[0]['uuid'] if m else '')")
if [ -z "$PROJECT_UUID" ]; then
	RESP=$(api POST /projects -d '{"name":"rpim"}') || {
		echo "project creation failed — full projects list for diagnosis:" >&2
		api GET /projects >&2 || true
		exit 1
	}
	PROJECT_UUID=$(printf '%s' "$RESP" | jqpy "print(json.load(sys.stdin)['uuid'])")
	echo "→ project created: $PROJECT_UUID"
else
	echo "→ project exists: $PROJECT_UUID"
fi

# Shared secrets generated once per provisioning run (INTERNAL_TOKEN must be
# identical on both legs).
PGPASS=$(openssl rand -hex 32)
APPKEY=$(openssl rand -hex 32)
JWT=$(openssl rand -hex 32)
ITOK=$(openssl rand -hex 32)

find_app() { # name -> uuid or empty
	api GET /applications | jqpy "
d=json.load(sys.stdin)
m=[a for a in d if a.get('name')=='$1']
print(m[0]['uuid'] if m else '')"
}

create_app() { # name compose_path -> uuid
	local name="$1" compose="$2"
	api POST /applications/public -d "{
      \"project_uuid\": \"$PROJECT_UUID\",
      \"server_uuid\": \"$SERVER_UUID\",
      \"environment_name\": \"production\",
      \"name\": \"$name\",
      \"git_repository\": \"$REPO_URL\",
      \"git_branch\": \"$BRANCH\",
      \"build_pack\": \"dockercompose\",
      \"docker_compose_location\": \"$compose\",
      \"connect_to_docker_network\": true,
      \"instant_deploy\": false
    }" | jqpy "print(json.load(sys.stdin)['uuid'])"
}

set_envs() { # uuid, then KEY=VALUE args
	local uuid="$1"
	shift
	for kv in "$@"; do
		api POST "/applications/$uuid/envs" \
			-d "{\"key\":\"${kv%%=*}\",\"value\":\"${kv#*=}\",\"is_preview\":false}" >/dev/null ||
			echo "   (env ${kv%%=*} may already exist — leaving as-is)"
	done
}

upsert_env() { # uuid key value — create OR update (used for corrective overrides)
	local uuid="$1" key="$2" val="$3"
	api POST "/applications/$uuid/envs" \
		-d "{\"key\":\"$key\",\"value\":\"$val\",\"is_preview\":false}" >/dev/null 2>&1 ||
		api PATCH "/applications/$uuid/envs" \
			-d "{\"key\":\"$key\",\"value\":\"$val\"}" >/dev/null ||
		echo "!! failed to upsert env $key on $uuid" >&2
	echo "→ env $key upserted" >&2
}

provision_leg() { # name compose_path env... — progress on stderr, uuid on stdout
	local name="$1" compose="$2"
	shift 2
	local uuid created=0
	uuid=$(find_app "$name")
	if [ -z "$uuid" ]; then
		uuid=$(create_app "$name" "$compose") || {
			echo "!! creating $name failed — aborting" >&2
			exit 1
		}
		[ -n "$uuid" ] || {
			echo "!! empty uuid returned for $name — aborting" >&2
			exit 1
		}
		created=1
		echo "→ $name created: $uuid" >&2
	else
		echo "→ $name exists: $uuid (envs untouched)" >&2
		# Corrective: compose files moved to the repo root (Coolify cannot build
		# contexts that point ABOVE the compose file's directory).
		api PATCH "/applications/$uuid" -d "{\"docker_compose_location\": \"$compose\"}" >/dev/null &&
			echo "→ $name compose location set to $compose" >&2 ||
			echo "!! failed to update compose location for $name" >&2
	fi
	# Corrective for BOTH new and existing apps: compose resources are NOT
	# attached to Coolify's predefined network by default — the per-resource
	# "Connect To Predefined Network" flag must be on, or cross-leg
	# container-name DNS fails instantly (ADR 0029, third amendment).
	api PATCH "/applications/$uuid" -d '{"connect_to_docker_network": true}' >/dev/null &&
		echo "→ $name connected to predefined docker network" >&2 ||
		echo "!! failed to set connect_to_docker_network for $name" >&2
	if [ "$created" = 1 ]; then set_envs "$uuid" "$@"; fi
	# Corrective overrides apply to EXISTING apps too (host-port collisions on
	# the server: Coolify panel owns 8000, Traefik owns 8080). The cross-leg
	# URLs are corrective as well: the first provisioning stored WireGuard IPs
	# (10.66.x) as Coolify envs, which kept overriding the compose defaults
	# after ADR 0025/0029 moved to container-name URLs — that stale override
	# broke every brain ingest in production.
	for kv in "$@"; do
		case "${kv%%=*}" in
		CORE_PORT | GATEWAY_PORT | CORE_BIND | GATEWAY_BIND | GATEWAY_URL | RENDERER_URL | CORE_API_URL)
			upsert_env "$uuid" "${kv%%=*}" "${kv#*=}"
			;;
		esac
	done
	api GET "/deploy?uuid=$uuid" >/dev/null &&
		echo "→ $name deploy triggered" >&2 ||
		echo "!! deploy trigger failed for $name (see error above)" >&2
	echo "$uuid"
}

# Cross-leg URLs use container-name DNS on Coolify's predefined network
# (ADR 0029; container names pinned in the compose files). When the Iran VPS
# returns (ADR 0025), the WireGuard IPs go back here.
IRAN_UUID=$(provision_leg "rpim-iran-leg" "/docker-compose.iran.yml" \
	"APP_ENV=production" \
	"POSTGRES_USER=rpim" "POSTGRES_PASSWORD=$PGPASS" "POSTGRES_DB=rpim" \
	"DATABASE_URL=postgresql://rpim:$PGPASS@postgres:5432/rpim" \
	"APP_SECRET_KEY=$APPKEY" "JWT_SECRET=$JWT" "INTERNAL_TOKEN=$ITOK" \
	"GATEWAY_URL=http://rpim-model-gateway:8080" \
	"RENDERER_URL=http://rpim-renderer:8091" \
	"CORE_BIND=127.0.0.1" "CORE_PORT=18000" | tail -1)

US_UUID=$(provision_leg "rpim-us-leg" "/docker-compose.us.yml" \
	"APP_ENV=production" \
	"INTERNAL_TOKEN=$ITOK" \
	"CORE_API_URL=http://rpim-core-api:8000" \
	"GATEWAY_BIND=127.0.0.1" "GATEWAY_PORT=18080" | tail -1)

echo
echo "Done. Resource UUIDs (for GitHub repo variables COOLIFY_IRAN_UUID / COOLIFY_US_UUID):"
echo "  iran-leg: $IRAN_UUID"
echo "  us-leg:   $US_UUID"
echo "Watch deployments in the Coolify UI, or: GET /api/v1/applications/{uuid}"

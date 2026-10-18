#!/usr/bin/env bash
# Provision and Deploy rpim-tv-pipeline on Coolify
set -euo pipefail

: "${COOLIFY_URL:?set COOLIFY_URL}"
: "${COOLIFY_TOKEN:?set COOLIFY_TOKEN}"

REPO_URL="${REPO_URL:-https://github.com/ashoorijahanban1-dev/rpim-tv-pipeline}"
BRANCH="${BRANCH:-master}"

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
	RESP=$(api POST /projects -d '{"name":"rpim"}')
	PROJECT_UUID=$(printf '%s' "$RESP" | jqpy "print(json.load(sys.stdin)['uuid'])")
	echo "→ project created: $PROJECT_UUID"
else
	echo "→ project exists: $PROJECT_UUID"
fi

find_app() {
	api GET /applications | jqpy "
d=json.load(sys.stdin)
m=[a for a in d if a.get('name')=='$1']
print(m[0]['uuid'] if m else '')"
}

create_app() {
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

upsert_env() {
	local uuid="$1" key="$2" val="$3"
	api POST "/applications/$uuid/envs" \
		-d "{\"key\":\"$key\",\"value\":\"$val\",\"is_preview\":false}" >/dev/null 2>&1 || \
	api PATCH "/applications/$uuid/envs" \
		-d "{\"key\":\"$key\",\"value\":\"$val\"}" >/dev/null 2>&1 || \
	echo "!! failed to upsert env $key on $uuid" >&2
	echo "→ env $key configured" >&2
}

APP_NAME="rpim-tv-pipeline"
COMPOSE_PATH="/docker-compose.us.yml"

APP_UUID=$(find_app "$APP_NAME")
if [ -z "$APP_UUID" ]; then
	APP_UUID=$(create_app "$APP_NAME" "$COMPOSE_PATH")
	echo "→ $APP_NAME created: $APP_UUID"
else
	echo "→ $APP_NAME exists: $APP_UUID"
	api PATCH "/applications/$APP_UUID" -d "{
		\"git_repository\": \"$REPO_URL\",
		\"git_branch\": \"$BRANCH\",
		\"docker_compose_location\": \"$COMPOSE_PATH\",
		\"connect_to_docker_network\": true
	}" >/dev/null
	echo "→ $APP_NAME updated repo/compose settings"
fi

api PATCH "/applications/$APP_UUID" -d '{"connect_to_docker_network": true}' >/dev/null || true

PG_PASS="${POSTGRES_PASSWORD:-$(openssl rand -hex 24)}"
upsert_env "$APP_UUID" "ENGINE_PORT" "8090"
upsert_env "$APP_UUID" "ENGINE_BIND" "0.0.0.0"
upsert_env "$APP_UUID" "POSTGRES_USER" "coolify"
upsert_env "$APP_UUID" "POSTGRES_PASSWORD" "$PG_PASS"

if [ -n "${GEMINI_API_KEY:-}" ]; then
	upsert_env "$APP_UUID" "GEMINI_API_KEY" "$GEMINI_API_KEY"
	upsert_env "$APP_UUID" "GEMINI_KEY_POOL" "$GEMINI_API_KEY"
fi

if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
	upsert_env "$APP_UUID" "DEEPSEEK_API_KEY" "$DEEPSEEK_API_KEY"
fi

echo "→ Triggering deploy for $APP_NAME ($APP_UUID)..."
DEPLOY_RESP=$(api GET "/deploy?uuid=$APP_UUID")
echo "→ Deploy triggered: $DEPLOY_RESP"

echo "PIPELINE_APP_UUID=$APP_UUID"

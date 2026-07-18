#!/usr/bin/env bash
# Prints ready-to-paste Coolify environment blocks for BOTH legs with freshly
# generated secrets (INTERNAL_TOKEN identical across legs, DATABASE_URL
# pre-composed). Run this on YOUR machine / server shell:
#
#   bash scripts/print-coolify-env.sh
#
# Paste each block into the matching Coolify resource → Environment Variables
# (Developer view / bulk edit). The output CONTAINS SECRETS — never paste it
# into chats, issues, or commits (CLAUDE.md rule 4).
set -euo pipefail

PGPASS=$(openssl rand -hex 32)
APPKEY=$(openssl rand -hex 32)
JWT=$(openssl rand -hex 32)
ITOK=$(openssl rand -hex 32)

cat <<EOF
############################################################
# IRAN leg — Coolify resource: docker-compose.iran.yml
############################################################
APP_ENV=production
POSTGRES_USER=rpim
POSTGRES_PASSWORD=$PGPASS
POSTGRES_DB=rpim
DATABASE_URL=postgresql://rpim:$PGPASS@postgres:5432/rpim
APP_SECRET_KEY=$APPKEY
JWT_SECRET=$JWT
INTERNAL_TOKEN=$ITOK
GATEWAY_URL=http://10.66.0.2:8080
# before WireGuard is up keep loopback; after: CORE_BIND=10.66.0.1
CORE_BIND=127.0.0.1
# Super Admin allowlist (M18, ADR 0035) — operator mandate:
ADMIN_EMAILS=info@ahmadi98.ir
# Radars (M19, ADR 0036) — flip to live once feed URLs are curated:
TRENDS_MODE=fake
TRENDS_FEED_URLS=
AI_NEWS_MODE=fake
AI_NEWS_FEED_URLS=
# CHANNEL_SECRET_KEY is deliberately NOT here (ADR 0033): it is set ONCE in
# Coolify — regenerating it would orphan every sealed channel secret.

############################################################
# US leg — Coolify resource: docker-compose.us.yml
############################################################
APP_ENV=production
# must be IDENTICAL to the iran leg:
INTERNAL_TOKEN=$ITOK
CORE_API_URL=http://10.66.0.1:8000
# before WireGuard is up keep loopback; after: GATEWAY_BIND=10.66.0.2
GATEWAY_BIND=127.0.0.1
# M3 (model gateway milestone) fills these:
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
ANTHROPIC_API_KEY=
MODEL_T1=
MODEL_T2=gemini:gemini-2.5-flash
# openai_compat adapter (M17, ADR 0034) — any OpenAI-compatible reseller:
OPENAI_COMPAT_BASE_URL=
OPENAI_COMPAT_API_KEY=
EOF

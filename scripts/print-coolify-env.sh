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
# IRAN leg — Coolify resource: infra/docker-compose.iran.yml
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

############################################################
# US leg — Coolify resource: infra/docker-compose.us.yml
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
MODEL_T2=
EOF

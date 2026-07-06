# RPIM monorepo — canonical commands (CLAUDE.md §Commands)
# Legs: iran (user-facing) / us (model gateway). Coolify is the deploy path on
# real servers; the `local` compose profile adds our own Caddy for local dev + CI.

# --env-file feeds compose ${VAR} interpolation locally (Coolify UI does the
# same in production); the wildcard keeps commands working pre-env-init.
ENVFILE_IRAN = $(if $(wildcard .env.iran),--env-file .env.iran,)
ENVFILE_US   = $(if $(wildcard .env.us),--env-file .env.us,)
COMPOSE_IRAN = docker compose $(ENVFILE_IRAN) -f docker-compose.iran.yml -p rpim-iran --profile local
COMPOSE_US   = docker compose $(ENVFILE_US) -f docker-compose.us.yml -p rpim-us --profile local

.PHONY: env-init up-iran up-us down-iran down-us test lint fmt healthcheck

## Generate gitignored .env.iran / .env.us from the committed examples.
## Secret-shaped fields are FILLED with `openssl rand -hex 32`, never left blank.
env-init:
	@for leg in iran us; do \
		if [ -f .env.$$leg ]; then echo ".env.$$leg exists — leaving untouched"; continue; fi; \
		cp .env.$$leg.example .env.$$leg; \
		for var in APP_SECRET_KEY JWT_SECRET INTERNAL_TOKEN POSTGRES_PASSWORD; do \
			if grep -q "^$$var=" .env.$$leg; then \
				val=$$(openssl rand -hex 32); \
				sed -i "s|^$$var=.*|$$var=$$val|" .env.$$leg; \
			fi; \
		done; \
		sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=rpim|" .env.$$leg; \
		sed -i "s|^POSTGRES_DB=.*|POSTGRES_DB=rpim|" .env.$$leg; \
		if grep -q "^POSTGRES_PASSWORD=" .env.$$leg && grep -q "^DATABASE_URL=" .env.$$leg; then \
			pw=$$(sed -n 's/^POSTGRES_PASSWORD=//p' .env.$$leg); \
			sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://rpim:$$pw@postgres:5432/rpim|" .env.$$leg; \
		fi; \
		echo "generated .env.$$leg"; \
	done; \
	if [ -f .env.iran ] && [ -f .env.us ]; then \
		tok=$$(sed -n 's/^INTERNAL_TOKEN=//p' .env.iran); \
		if [ -n "$$tok" ]; then sed -i "s|^INTERNAL_TOKEN=.*|INTERNAL_TOKEN=$$tok|" .env.us; fi; \
	fi

up-iran: env-init
	$(COMPOSE_IRAN) up -d --build --wait

up-us: env-init
	$(COMPOSE_US) up -d --build --wait

down-iran:
	$(COMPOSE_IRAN) down

down-us:
	$(COMPOSE_US) down

## Fast + docker-free: the PostToolUse hook runs this after every file edit.
test:
	@uv run pytest

lint:
	@uv run ruff check .
	@if [ -f apps/dashboard/package.json ] && [ -d apps/dashboard/node_modules ]; then \
		cd apps/dashboard && npm run lint --silent; \
	fi

fmt:
	@uv run ruff format .
	@uv run ruff check --fix .

healthcheck:
	@bash scripts/crossleg-healthcheck.sh $${MODE:-local}

## M10 ops (docs/ops/runbook.md): encrypted backup + kill-switch drill.
backup:
	@bash scripts/backup.sh

kill-drill:
	@uv run pytest apps/core-api/tests/test_m10_kill_drill.py -q

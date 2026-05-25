#!/usr/bin/env bash
set -euo pipefail

# Start hermes-agent in Docker with personal, safer defaults
HERMES_UID=${HERMES_UID:-$(id -u)}
HERMES_GID=${HERMES_GID:-$(id -g)}
export HERMES_UID HERMES_GID

# Compose files: base plus optional override when local secret files are present
COMPOSE_ARGS=("-f" "docker-compose.personal.yml")
OVERRIDE_FILE=""

SECRETS_DIR="${HOME}/.hermes/secrets"
if [ -d "$SECRETS_DIR" ]; then
  OVERRIDE_CONTENT="version: \"3.8\"\nservices:\n  hermes:\n    volumes:\n"
  if [ -f "$SECRETS_DIR/hermes_auth.json" ]; then
    OVERRIDE_CONTENT+="      - \"${SECRETS_DIR}/hermes_auth.json:/run/secrets/HERMES_AUTH_JSON_BOOTSTRAP:ro\"\n"
  fi
  if [ -f "$SECRETS_DIR/api_server_key" ]; then
    OVERRIDE_CONTENT+="      - \"${SECRETS_DIR}/api_server_key:/run/secrets/API_SERVER_KEY:ro\"\n"
  fi

  # Only write an override file if it contains secret mappings
  if echo "$OVERRIDE_CONTENT" | grep -q "/run/secrets/"; then
    OVERRIDE_FILE=$(mktemp /tmp/docker-compose.hermes-override.XXXX.yml)
    printf "%b" "$OVERRIDE_CONTENT" > "$OVERRIDE_FILE"
    COMPOSE_ARGS+=("-f" "$OVERRIDE_FILE")
    # Ensure cleanup on exit
    trap 'rm -f "$OVERRIDE_FILE"' EXIT
    echo "Using secret override file $OVERRIDE_FILE"
  fi
fi

echo "Starting hermes-agent (personal) in Docker using docker-compose.personal.yml"
docker compose "${COMPOSE_ARGS[@]}" up -d --build

echo "Done. Use 'docker logs -f hermes-personal' to follow logs or 'docker compose -f docker-compose.personal.yml down' to stop."

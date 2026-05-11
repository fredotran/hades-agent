Docker helper files for hermes-agent

Produced files:
- Dockerfile.hermes      # multi-stage builder -> small runtime image
- Dockerfile.dev         # editable / dev image (pip -e)
- docker-compose.hermes.yml  # simple production compose (named volume)
- docker-compose.dev.yml     # development compose (bind-mount source)

Quick start (production, build with extras):
  docker-compose -f docker-compose.hermes.yml build --pull
  docker-compose -f docker-compose.hermes.yml up -d

Or build directly with build-arg extras:
  docker build -f Dockerfile.hermes --build-arg EXTRAS="web,cli" -t hermes:latest .

Dev mode (editable install, mounts source):
  docker-compose -f docker-compose.dev.yml up --build

Secrets & API keys:
- Pass API keys at runtime via environment variables (compose env or .env) or Docker secrets.
  Do NOT bake secrets into images.

Persistence:
- HERMES_HOME is persisted to a named volume (docker-compose.hermes.yml) or host path (dev mount).

Notes:
- Keep EXTRAS minimal to avoid heavy native deps (voice, faster-whisper).
- To run the TUI interactively in dev: docker-compose -f docker-compose.dev.yml run --service-ports hermes

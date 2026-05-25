This repository is a personal fork of Nous Research's hermes-agent.

Purpose
-------
This fork exists to apply personal security hardening and operational defaults for running Hermes Agent privately (container isolation, secrets handling, capability reduction, restricted networking, and CI scanning).

Original
--------
https://github.com/NousResearch/hermes-agent

Notes
-----
Do not publish secrets or credentials in this fork. Keep credentials in host-only locations and inject via Docker secrets or environment variables at runtime.

Docker secrets
--------------
This fork adds convenience support for mounting secret files from the host into the container at /run/secrets/*. The included scripts/run-local.sh will automatically generate a Compose override to bind-mount:

  - ~/.hermes/secrets/hermes_auth.json -> /run/secrets/HERMES_AUTH_JSON_BOOTSTRAP (used to bootstrap auth.json on first run)
  - ~/.hermes/secrets/api_server_key -> /run/secrets/API_SERVER_KEY

Create the directory ~/.hermes/secrets and place those files (with restrictive permissions) if you want the helper script to mount them for you. Prefer Docker secrets or a secrets manager in production.

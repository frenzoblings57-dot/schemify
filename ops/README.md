# Operator notes (Beta sandbox)

Schemify is a stateless Python backend. It needs no secrets, no database and no outbound network.

## Run
Build and start (rootless Docker, work folder `~/schemify-beta`):
```bash
git clone https://github.com/frenzoblings57-dot/schemify.git ~/schemify-beta/backend-src
cd ~/schemify-beta/backend-src
export GIT_COMMIT=$(git rev-parse --short HEAD)
docker compose up -d --build
```
The backend is published on `127.0.0.1:28080` only. Never publish it on `0.0.0.0`.

## Check
```bash
curl -s 127.0.0.1:28080/v1/health
curl -s 127.0.0.1:28080/v1/version
python3 smoke_test.py http://127.0.0.1:28080
```

## Update and roll back
```bash
git pull && docker compose up -d --build        # update
git checkout <old-commit> && docker compose up -d --build   # roll back
```
Updating the backend never touches the supplier operator key, Redis, or the RelayMiner.

## Stop
```bash
docker compose down
```

## Limits
- 1 GB RAM and 0.7 CPU for the whole sandbox. This container uses roughly 100 MB with 2 workers.
- Ports: only `28000-28099` on the host. RelayMiner is `172.17.0.1:28545`.
- Do not publish Redis, metrics or health ports.

## Incidents
Report to the service owner (Frenzo). Include the output of `docker compose logs --tail 100 schemify`. Logs never contain request bodies.

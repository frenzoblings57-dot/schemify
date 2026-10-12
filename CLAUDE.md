## Deployment environment (hackathon Beta sandbox)
- Target: Pocket Beta/TestNet ONLY. Never MainNet.
- Server: frenzo@135.181.248.55, no sudo, rootless Docker
  (DOCKER_HOST=unix:///run/user/<uid>/docker.sock). Work folder ~/schemify-beta.
- Allowed host ports: 28000-28099. RelayMiner published as 172.17.0.1:28545; everything else 127.0.0.1 only.
- Public HTTPS: https://beta.schemify.com.ng -> 172.17.0.1:28545 (operator's Caddy container).
- Resource limits: 1 GB RAM total, 0.7 CPU. Keep images slim; Redis maxmemory well under 256mb.
- Do not publish Redis/metrics/health ports. Never bind 0.0.0.0. Ports < 1024 are unavailable.
- Never print, commit, or ask for private keys. All signing/staking happens in PSM by the human.
- Stop and ask before any transaction, stake, or key import.

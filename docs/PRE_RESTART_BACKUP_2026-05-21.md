# Pre-Restart Backup - 2026-05-21

This checkpoint was created immediately after the demo UI polish and Remotion
animation-skill cleanup were synced to the AI server.

## Git Checkpoint

- Commit: `0ebe6f5` - `Polish demo UI and Remotion animation skill`
- Remote: `https://github.com/autonomouscereal/Agentic-IT`
- Branch: `main`

## Local Credential Vault

The Windows server-manager credential vault was integrity-checked and backed up
with the `vault-backup` skill.

- Checkpoint: `2026-05-22_000130`
- Credentials verified: `56`
- Secret values were not written to this document.

## AI Server Backup

- Server: `ai` (`192.168.50.222`)
- Backup path: `/home/cereal/backups/agentic-it-pre-restart-20260521-180219`
- Backup size: `3.5G`
- Database dump files: `18`
- Docker volume archives: `75`
- Files manifest: `/home/cereal/backups/agentic-it-pre-restart-20260521-180219/metadata/files.txt`
- SHA256 manifest: `/home/cereal/backups/agentic-it-pre-restart-20260521-180219/metadata/sha256sums.txt`

Included:

- Full live source tree archive.
- Live `.git` archive.
- Docker container, image, volume, and network inventory.
- Docker inspect metadata for containers and volumes.
- Resolved dashboard Docker Compose config.
- Dashboard compose logs.
- Dashboard PostgreSQL dump.
- Agent memory PostgreSQL dump.
- Generic PostgreSQL/MySQL dump attempts for running containers.
- All Docker named volume archives.
- `/home/cereal/.agents`, `/home/cereal/.codex`, and `/home/cereal/.claude`
  archives when present.

## Backup Warnings

The backup completed successfully. Warnings were from generic best-effort dump
attempts against containers that are not the authoritative database container or
do not expose dump credentials in their runtime environment:

- `php-fpm-mailcow-api` MySQL dump attempt failed.
- `sogo-mailcow` MySQL dump attempt failed.
- `gitlab` PostgreSQL dump attempt failed.
- `itop-deployment-itop-1` MySQL dump attempt failed.

These are covered by the Docker volume archives, and the dashboard/agent-memory
PostgreSQL dumps completed separately.

## Post-Backup Health

Post-backup checks:

- Dashboard health: `ok`
- Active agents: `0`
- Queued depth: `0`
- Runner processes: none active
- Max concurrent agents: `5`
- AI proxy: `ok` on port `4001`
- Active model route at backup time: `external`
- Proxy providers visible: `lmstudio`, `nous`, `openrouter`

## Restart Note

After a server restart, Codex OAuth may need to be re-brokered for the Codex
harness if the runtime session is not preserved. Hermes/local routing and the
AI proxy configuration are backed up with the server environment.

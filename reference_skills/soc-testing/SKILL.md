---
name: soc-testing
description: Zeek and Suricata SOC testing environment management on AI Server (192.168.50.222). Use when checking container status, viewing logs, or managing the security monitoring stack.
allowed-tools: Read Bash
---

# SOC Testing Environment - Skill

This skill manages the Zeek + Suricata SOC testing deployment.

## Quick Start Commands

### Check Container Status
```bash
cd /home/cereal/SOC_TESTING && docker compose -f docker-compose.yml ps
```

### View Suricata Logs (eve.json)
```bash
docker exec suricata-soc tail -20 /var/log/suricata/eve.json
```

### Restart Containers
```bash
cd /home/cereal/SOC_TESTING && ./soc-start.sh
```

## Management Scripts

| Script | Purpose |
|--------|---------|
| `soc-start.sh` | Start containers and Suricata capture |
| `soc-test.py` | Run health checks on both containers |
| `soc-collector.py` | Download logs locally |

## Container Details

### Zeek (zeek-soc)
- Image: zeek/zeek:latest
- Ports: 26001 (API), 26002 (Logs)
- Network: soc-network (bridge)

### Suricata (suricata-soc)
- Image: jasonish/suricata:latest
- Network Mode: host
- Capture Interface: enp129s0f0

## Log Locations

| Service | Log Path |
|---------|----------|
| Zeek | /var/log/zeek/ |
| Suricata | /var/log/suricata/eve.json |

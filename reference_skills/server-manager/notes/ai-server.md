# AI Server Notes

## Basic Information
- **IP Address:** 192.168.50.222
- **Username:** cereal
- **SSH Port:** 22
- **Password Authentication:** Enabled (stored in encrypted credential vault)

## Purpose
AI/ML workloads, inference services, and model deployment infrastructure.

## Key Services Running
| Service | Description |
|---------|-------------|
| GPU Workloads | CUDA-accelerated ML processing |
| Model Serving | TensorFlow/PyTorch inference endpoints |
| Vector Database | RAG-enabled knowledge storage |
| API Gateway | AI feature exposure to applications |

## Infrastructure Layout
```
/var/
├── ai-models/        # Machine learning models
├── inference/        # Inference logs and outputs
└── data/             # Training and inference datasets

/opt/
└── ml-services/      # ML service deployments
```

## Common Commands

### Connection & Monitoring
```bash
# Interactive SSH session
ssh cereal@192.168.50.222

# Check GPU utilization
nvidia-smi

# Monitor running containers
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### AI/ML Operations
```bash
# View inference logs
tail -f /var/log/inference.log

# Check model serving status
curl http://localhost:8080/health

# Monitor GPU memory and compute utilization
watch -n 5 nvidia-smi d -q -d MEMORY,UTILIZATION
```

### Model Management
```bash
# List available models
docker images | grep -E 'tensorflow|pytorch|model'

# Check model inference latency
ab -n 1000 -c 10 http://localhost:8080/inference

# Review training pipeline status
journalctl -u ml-training --since "24 hours ago"
```

## Performance Monitoring

### GPU Metrics
- **Utilization:** Real-time compute and memory usage
- **Temperature:** Thermal monitoring for stability
- **Power:** Power consumption tracking

### Inference Metrics
- Latency measurements (p50, p95, p99)
- Throughput (requests per second)
- Error rates and retry statistics

## Maintenance Tasks

| Frequency | Task |
|-----------|------|
| Daily | Monitor GPU utilization and inference logs |
| Weekly | Review model deployments and updates |
| Monthly | Check storage capacity and optimize datasets |
| Quarterly | Update ML frameworks and security patches |

## Network Configuration
- **Firewall:** Port 22 (SSH), 8080 (API), 6000+ (ML services)
- **Model Registry:** Centralized model versioning and deployment
- **Monitoring:** Prometheus/Grafana for metrics visualization

---
*Last updated: 2026-03-09*

FROM python:3.11-slim

RUN mkdir -p /var/lib/siem-ticket-bridge /var/log/siem-ticket-bridge

WORKDIR /app
COPY ../siem_ticket_bridge/ ./siem_ticket_bridge/
COPY ../severity_map.json ./

RUN pip install --no-cache-dir --upgrade pip

EXPOSE 8080

ENTRYPOINT ["python", "-m"]
CMD ["siem_ticket_bridge.bridge"]

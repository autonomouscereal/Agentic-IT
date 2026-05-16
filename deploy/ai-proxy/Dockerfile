FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ai_proxy.py .

ENV PROXY_PORT=4001
CMD ["python", "/app/ai_proxy.py"]

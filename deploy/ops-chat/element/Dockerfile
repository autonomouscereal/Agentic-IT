ARG ELEMENT_WEB_IMAGE=vectorim/element-web:latest
FROM ${ELEMENT_WEB_IMAGE}

USER root
COPY config.json.template /app/config.json.template
COPY render_config.sh /docker-entrypoint.d/99-render-agentic-ops-config.sh
RUN chmod +x /docker-entrypoint.d/99-render-agentic-ops-config.sh

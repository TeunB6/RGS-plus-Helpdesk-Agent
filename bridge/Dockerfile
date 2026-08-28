FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Requirements first so dependency layers survive code edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Non-root: this process only needs to make outbound HTTP calls.
RUN useradd --create-home --uid 10001 bridge
USER bridge

EXPOSE 8081

# No healthcheck against /readyz here — readiness depends on the agent
# container, and a bridge marked unhealthy because its upstream is booting
# would get restarted for no reason. Orchestrators should probe /healthz for
# liveness and /readyz for traffic.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]

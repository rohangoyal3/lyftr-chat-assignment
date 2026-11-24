FROM python:3.12-slim-bookworm AS build
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    DATABASE_URL=sqlite:////data/app.db
WORKDIR /service
RUN mkdir -p /data
COPY --from=build /opt/venv /opt/venv
COPY app ./app
EXPOSE 8000
CMD ["python", "-m", "app"]

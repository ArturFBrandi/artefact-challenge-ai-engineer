# Convenience for running without uv:
#   docker build -t emporio .
#   docker run --rm -p 8000:8000 --env-file .env -e WEB_HOST=0.0.0.0 emporio
FROM python:3.12-slim AS base
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv==0.12.21
WORKDIR /app

FROM base AS build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --create-home app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY src ./src
COPY config ./config
COPY data ./data
RUN mkdir var && chown app var
USER app
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/src WEB_HOST=0.0.0.0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "emporio.web"]

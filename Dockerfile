FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH

WORKDIR /app
COPY --from=builder /install /usr/local
COPY migrations ./migrations
COPY scripts/migrate.py ./scripts/migrate.py
COPY fixtures ./fixtures

RUN groupadd --gid 65532 opspilot \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin opspilot

USER 65532:65532
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "opspilot.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

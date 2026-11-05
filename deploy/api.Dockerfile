FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.14.10-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies go in a layer of their own, so editing source doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY LICENSE README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14.10-slim-trixie AS production
RUN useradd --create-home --uid 10001 ledgerlens
WORKDIR /app
COPY --from=build /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"
USER ledgerlens
EXPOSE 8000
CMD ["uvicorn", "ledgerlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM registry.access.redhat.com/ubi9/python-312

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/app-root \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /opt/app-root/src

COPY --chown=1001:0 pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=1001:0 backend ./backend
COPY --chown=1001:0 contracts ./contracts
RUN uv sync --locked --no-dev

EXPOSE 8080
ENTRYPOINT ["python", "-m", "backend"]
CMD ["api"]

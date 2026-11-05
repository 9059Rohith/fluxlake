ARG BUILDER_IMAGE=cgr.dev/chainguard/python:latest-dev@sha256:95d8cc85fad8acc8ebad357e1972f2a975c498a65406cd9b00bb2233371a94a2
ARG RUNTIME_IMAGE=cgr.dev/chainguard/python:latest@sha256:bf06e09413bec94d6489f0be783b8f9349339907b89e0f759d190d0b95ab2d8f
FROM ${BUILDER_IMAGE} AS build
USER 0
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install pip==26.2.2 \
    && /opt/venv/bin/python -m pip install --only-binary=:all: --no-deps -r requirements.lock \
    && /opt/venv/bin/python -m pip check
COPY pyproject.toml ./
COPY src ./src
COPY sql ./sql
RUN --mount=type=cache,target=/root/.cache/pip /opt/venv/bin/python -m pip install --no-deps . \
    && mkdir /data && chown 10001:10001 /data \
    && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel
FROM build AS verify
USER 0
COPY requirements-test.lock requirements-dev.lock ./
RUN --mount=type=cache,target=/root/.cache/pip python -m venv /opt/testtools \
    && /opt/testtools/bin/python -m pip install --no-deps -r requirements-test.lock
COPY tests ./tests
COPY scripts/verify_build.py ./scripts/verify_build.py
COPY Dockerfile .dockerignore .vercelignore ./
ENV PYTHONPATH=/opt/venv/lib/python3.15/site-packages
RUN --network=none /opt/testtools/bin/python scripts/verify_build.py --output /verification/receipt.json
ENTRYPOINT []
CMD ["/opt/testtools/bin/python", "scripts/verify_build.py", "--output", "/verification/receipt.json"]

FROM ${RUNTIME_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:/usr/bin PORT=8080 FLUXLAKE_ROOT=/data
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/sql ./sql
COPY --from=verify /verification/receipt.json /app/build-verification.json
COPY --from=build --chown=10001:10001 /data /data
USER 10001:10001
EXPOSE 8080
ENTRYPOINT []
CMD ["fluxlake", "api", "--host", "0.0.0.0"]

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-deps -r requirements.lock
COPY src ./src
COPY sql ./sql
RUN pip install --no-deps . && useradd --uid 10001 --create-home fluxlake && mkdir /data && chown fluxlake:fluxlake /data
USER 10001
EXPOSE 8000
CMD ["fluxlake", "api", "--host", "0.0.0.0", "--root", "/data"]

FROM python:3.12-slim

ARG DBT_CORE_VERSION=1.12.3
ARG DBT_ATHENA_VERSION=1.11.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir "dbt-core==${DBT_CORE_VERSION}" "dbt-athena==${DBT_ATHENA_VERSION}"

COPY dbt /app/dbt
COPY deploy/dbt/profiles.yml /app/profiles.yml

ENTRYPOINT ["dbt"]

CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app"]
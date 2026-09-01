FROM python:3.12-slim

ARG DBT_CORE_VERSION=1.12.3
ARG DBT_ATHENA_VERSION=1.11.0
ARG OPENLINEAGE_VERSION=1.52.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "dbt-core==${DBT_CORE_VERSION}" \
    "dbt-athena==${DBT_ATHENA_VERSION}" \
    "openlineage-python[fsspec]==${OPENLINEAGE_VERSION}" \
    "fsspec[s3]"

COPY dbt /app/dbt
COPY lineage /app/lineage
COPY deploy/dbt/profiles.yml /app/profiles.yml
COPY jobs/dbt/run_dbt_with_lineage.py /app/run_dbt_with_lineage.py

ENTRYPOINT ["python", "/app/run_dbt_with_lineage.py"]

CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app"]

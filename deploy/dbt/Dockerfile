FROM python:3.12-slim

ARG DBT_CORE_VERSION=1.12.3
ARG DBT_ATHENA_VERSION=1.11.0
ARG OPENLINEAGE_VERSION=1.52.0
ARG BOTO3_VERSION=1.43.75
ARG BOTOCORE_VERSION=1.43.75
ARG PYATHENA_VERSION=3.34.0
ARG FSSPEC_VERSION=2026.6.0
ARG S3FS_VERSION=2026.6.0
ARG SCIKIT_LEARN_VERSION=1.9.1

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "dbt-core==${DBT_CORE_VERSION}" \
    "dbt-athena==${DBT_ATHENA_VERSION}" \
    "openlineage-python[fsspec]==${OPENLINEAGE_VERSION}" \
    "boto3==${BOTO3_VERSION}" \
    "botocore==${BOTOCORE_VERSION}" \
    "pyathena==${PYATHENA_VERSION}" \
    "fsspec==${FSSPEC_VERSION}" \
    "s3fs==${S3FS_VERSION}" \
    "scikit-learn==${SCIKIT_LEARN_VERSION}"

COPY dbt /app/dbt
COPY lineage /app/lineage
COPY deploy/dbt/profiles.yml /app/profiles.yml
COPY jobs/dbt/run_dbt_with_lineage.py /app/run_dbt_with_lineage.py
COPY jobs/ml /app/jobs/ml

ENTRYPOINT ["python", "/app/run_dbt_with_lineage.py"]

CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app"]

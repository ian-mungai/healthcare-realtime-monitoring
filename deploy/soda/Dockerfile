FROM python:3.12-slim

ARG SODA_ATHENA_VERSION=4.22.0
ARG OPENLINEAGE_VERSION=1.52.0
ARG GREAT_EXPECTATIONS_VERSION=1.22.0
ARG SQLALCHEMY_VERSION=1.4.54
ARG PYATHENA_VERSION=3.36.0
ARG BOTO3_VERSION=1.43.75
ARG BOTOCORE_VERSION=1.43.75
ARG FSSPEC_VERSION=2026.6.0
ARG S3FS_VERSION=2026.6.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "soda-athena==${SODA_ATHENA_VERSION}" \
    "openlineage-python[fsspec]==${OPENLINEAGE_VERSION}" \
    "great-expectations==${GREAT_EXPECTATIONS_VERSION}" \
    "sqlalchemy==${SQLALCHEMY_VERSION}" \
    "pyathena==${PYATHENA_VERSION}" \
    "boto3==${BOTO3_VERSION}" \
    "botocore==${BOTOCORE_VERSION}" \
    "fsspec==${FSSPEC_VERSION}" \
    "s3fs==${S3FS_VERSION}"

COPY lineage /app/lineage
COPY config/vital_signs.json /app/config/vital_signs.json
COPY services/__init__.py /app/services/__init__.py
COPY services/vital_signs.py /app/services/vital_signs.py
COPY deploy/soda/configuration.yml /app/configuration.yml
COPY data_quality/soda/contracts /app/contracts
COPY data_quality/soda/run_soda_with_lineage.py /app/run_soda_with_lineage.py
COPY data_quality/great_expectations/validate_processed_observations.py /app/validate_processed_observations.py
COPY scripts/run_soda_contracts_container.sh /app/run_soda_contracts.sh

RUN chmod +x /app/run_soda_contracts.sh

CMD ["python", "/app/run_soda_with_lineage.py"]

FROM python:3.12-slim

ARG SODA_ATHENA_VERSION=4.22.0
ARG OPENLINEAGE_VERSION=1.52.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "soda-athena==${SODA_ATHENA_VERSION}" \
    "openlineage-python[fsspec]==${OPENLINEAGE_VERSION}" \
    "fsspec[s3]"

COPY lineage /app/lineage
COPY deploy/soda/configuration.yml /app/configuration.yml
COPY data_quality/soda/contracts /app/contracts
COPY data_quality/soda/run_soda_with_lineage.py /app/run_soda_with_lineage.py
COPY scripts/run_soda_contracts_container.sh /app/run_soda_contracts.sh

RUN chmod +x /app/run_soda_contracts.sh

ENTRYPOINT ["python", "/app/run_soda_with_lineage.py"]

FROM python:3.12-slim

ARG SODA_ATHENA_VERSION=4.22.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir "soda-athena==${SODA_ATHENA_VERSION}"

COPY deploy/soda/configuration.yml /app/configuration.yml
COPY data_quality/soda/contracts /app/contracts
COPY scripts/run_soda_contracts_container.sh /app/run_soda_contracts.sh

RUN chmod +x /app/run_soda_contracts.sh

ENTRYPOINT ["/app/run_soda_contracts.sh"]
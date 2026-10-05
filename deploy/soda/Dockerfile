FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Hash-pinned lock compiled from requirements.in; pip refuses any package or file that does not match it.
COPY deploy/soda/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

COPY lineage /app/lineage
COPY config/vital_signs.json /app/config/vital_signs.json
COPY services/__init__.py /app/services/__init__.py
COPY services/vital_signs.py /app/services/vital_signs.py
COPY deploy/soda/configuration.yml /app/configuration.yml
COPY data_quality/soda/contracts /app/contracts
COPY data_quality/soda/run_soda_with_lineage.py /app/run_soda_with_lineage.py
COPY tools/__init__.py tools/process.py /app/tools/
COPY data_quality/great_expectations/validate_processed_observations.py /app/validate_processed_observations.py
COPY scripts/run_soda_contracts_container.sh /app/run_soda_contracts.sh

RUN chmod +x /app/run_soda_contracts.sh

CMD ["python", "/app/run_soda_with_lineage.py"]

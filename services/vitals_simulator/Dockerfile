FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/vitals_simulator/requirements.txt /tmp/requirements.txt

# Hash-pinned lock compiled from requirements.in; pip refuses any package or file that does not match it.
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

COPY services/__init__.py ./services/__init__.py
COPY services/vital_signs.py ./services/vital_signs.py
COPY services/vitals_simulator ./services/vitals_simulator
COPY config/vital_signs.json ./config/vital_signs.json

# The one-off FHIR setup task (docs/fhir-setup-tasks.md) runs from this image with its own command.
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/synthea_loader/__init__.py ./scripts/synthea_loader/__init__.py
COPY scripts/synthea_loader/src ./scripts/synthea_loader/src
COPY services/fhir_webhook/__init__.py ./services/fhir_webhook/__init__.py
COPY services/fhir_webhook/app/__init__.py services/fhir_webhook/app/config.py services/fhir_webhook/app/security.py ./services/fhir_webhook/app/
COPY services/fhir_webhook/app/subscription.py services/fhir_webhook/app/register_subscription.py ./services/fhir_webhook/app/
COPY jobs/fhir_setup ./jobs/fhir_setup

CMD ["python", "-m", "services.vitals_simulator.app.simulation.realtime_cohort_runner"]

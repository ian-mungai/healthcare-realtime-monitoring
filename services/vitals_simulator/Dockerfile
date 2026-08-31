FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/vitals_simulator/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/__init__.py ./services/__init__.py
COPY services/vitals_simulator ./services/vitals_simulator

CMD ["python", "-m", "services.vitals_simulator.app.simulation.realtime_cohort_runner"]
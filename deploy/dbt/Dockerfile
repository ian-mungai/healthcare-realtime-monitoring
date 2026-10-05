FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Hash-pinned lock compiled from requirements.in; pip refuses any package or file that does not match it.
COPY deploy/dbt/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

COPY dbt /app/dbt
COPY lineage /app/lineage
COPY deploy/dbt/profiles.yml /app/profiles.yml
COPY jobs/dbt/run_dbt_with_lineage.py /app/run_dbt_with_lineage.py
COPY tools/__init__.py tools/process.py tools/lint_sql.py tools/install_dbt_packages.py /app/tools/
RUN python -m tools.install_dbt_packages dbt /app/dbt
COPY jobs/ml /app/jobs/ml

ENTRYPOINT ["python", "/app/run_dbt_with_lineage.py"]

CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app"]

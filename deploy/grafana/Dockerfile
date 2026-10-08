# Grafana for the AWS warehouse: the local stack's pinned Grafana, the Athena data source plugin and the dashboards
# rendered for Athena. Build context: deploy/grafana, after
#   python -m scripts.grafana.render_dashboards --target aws --output deploy/grafana/rendered
# (scripts/infrastructure/push_images.sh does both). The admin password comes from Secrets Manager at task start.
FROM grafana/grafana:13.2.3@sha256:b28bae15e219c998fb0e0424ed724930cc61b1f61fb404d47c862f9a23f9e572

# grafana-athena-datasource 3.3.8 for linux/amd64, verified against the checksum grafana.com publishes for it.
ADD --checksum=sha256:c2987a621e1f6ecd88d19e13bd6108dcb9af4c5ff020ca6ddad5ecd0519001b3 \
    "https://grafana.com/api/plugins/grafana-athena-datasource/versions/3.3.8/download?os=linux&arch=amd64" \
    /tmp/athena.zip

USER root
RUN mkdir -p /opt/grafana/plugins \
    && unzip -q /tmp/athena.zip -d /opt/grafana/plugins \
    && rm /tmp/athena.zip \
    && chown -R grafana:root /opt/grafana/plugins
USER grafana

COPY provisioning/datasources/athena.yaml /etc/grafana/provisioning/datasources/athena.yaml
COPY provisioning/dashboards/healthcare_realtime.yaml /etc/grafana/provisioning/dashboards/healthcare_realtime.yaml
COPY rendered/ /etc/grafana/dashboards/

ENV GF_PATHS_PLUGINS=/opt/grafana/plugins \
    GF_AWS_ALLOWED_AUTH_PROVIDERS=default \
    GF_AWS_ASSUME_ROLE_ENABLED=false \
    GF_SECURITY_ADMIN_USER=admin \
    GF_USERS_ALLOW_SIGN_UP=false \
    GF_AUTH_ANONYMOUS_ENABLED=false \
    GF_ANALYTICS_REPORTING_ENABLED=false \
    GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_PLUGINS_PLUGIN_ADMIN_ENABLED=false

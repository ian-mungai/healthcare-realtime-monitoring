resource "aws_cloudwatch_metric_alarm" "openlineage_emission_failures" {
  alarm_name          = "healthcare-realtime-openlineage-emission-failures"
  alarm_description   = "A pipeline component could not deliver an OpenLineage event."
  namespace           = "HealthcareRealtime/OpenLineage"
  metric_name         = "EmissionFailure"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"
  alarm_actions      = [module.realtime_observability.alert_topic_arn]
  ok_actions         = [module.realtime_observability.alert_topic_arn]

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

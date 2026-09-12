locals {
  monitoring_enabled = var.enabled && var.desired_count > 0
  ecs_cluster_name   = basename(var.ecs_cluster_arn)
}

resource "aws_cloudwatch_log_metric_filter" "lineage_requests" {
  count = local.monitoring_enabled ? 1 : 0

  name           = "healthcare-realtime-openlineage-requests"
  pattern        = "{ $.routeKey = \"POST /api/v1/lineage\" }"
  log_group_name = aws_cloudwatch_log_group.api[0].name

  metric_transformation {
    name      = "LineageRequests"
    namespace = "HealthcareRealtime/OpenLineage"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "no_lineage_events" {
  count = local.monitoring_enabled ? 1 : 0

  alarm_name          = "healthcare-realtime-openlineage-no-events"
  alarm_description   = "No OpenLineage collector requests were received for 26 hours."
  namespace           = "HealthcareRealtime/OpenLineage"
  metric_name         = "LineageRequests"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 26
  datapoints_to_alarm = 26
  threshold           = 1
  comparison_operator = "LessThanThreshold"

  treat_missing_data = "breaching"
  alarm_actions      = [var.alarm_topic_arn]
  ok_actions         = [var.alarm_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "task_count" {
  count = local.monitoring_enabled ? 1 : 0

  alarm_name          = "healthcare-realtime-openlineage-task-count"
  alarm_description   = "The managed OpenLineage collector has fewer running tasks than configured."
  namespace           = "ECS/ContainerInsights"
  metric_name         = "RunningTaskCount"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = var.desired_count
  comparison_operator = "LessThanThreshold"

  dimensions = {
    ClusterName = local.ecs_cluster_name
    ServiceName = aws_ecs_service.marquez[0].name
  }

  treat_missing_data = "breaching"
  alarm_actions      = [var.alarm_topic_arn]
  ok_actions         = [var.alarm_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_targets" {
  count = local.monitoring_enabled ? 1 : 0

  alarm_name          = "healthcare-realtime-openlineage-unhealthy-targets"
  alarm_description   = "The OpenLineage collector load balancer has an unhealthy target."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  dimensions = {
    LoadBalancer = aws_lb.marquez[0].arn_suffix
    TargetGroup  = aws_lb_target_group.marquez[0].arn_suffix
  }

  treat_missing_data = "notBreaching"
  alarm_actions      = [var.alarm_topic_arn]
  ok_actions         = [var.alarm_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  count = local.monitoring_enabled ? 1 : 0

  alarm_name          = "healthcare-realtime-openlineage-target-5xx"
  alarm_description   = "The OpenLineage collector returned a server error."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  dimensions = {
    LoadBalancer = aws_lb.marquez[0].arn_suffix
    TargetGroup  = aws_lb_target_group.marquez[0].arn_suffix
  }

  treat_missing_data = "notBreaching"
  alarm_actions      = [var.alarm_topic_arn]
  ok_actions         = [var.alarm_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  count = local.monitoring_enabled ? 1 : 0

  alarm_name          = "healthcare-realtime-openlineage-api-5xx"
  alarm_description   = "API Gateway returned a server error for the OpenLineage collector."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  dimensions = {
    ApiId = aws_apigatewayv2_api.marquez[0].id
    Stage = aws_apigatewayv2_stage.development[0].name
  }

  treat_missing_data = "notBreaching"
  alarm_actions      = [var.alarm_topic_arn]
  ok_actions         = [var.alarm_topic_arn]

  tags = var.tags
}

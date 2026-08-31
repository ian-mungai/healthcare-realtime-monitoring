output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.mwaa.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs used by internet-facing resources"
  value = [
    aws_subnet.public_a.id,
    aws_subnet.public_b.id
  ]
}

output "private_subnet_ids" {
  description = "Private subnet IDs used by MWAA and private workloads"
  value = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]
}

output "security_group_id" {
  description = "Security group ID used by MWAA"
  value       = aws_security_group.mwaa.id
}
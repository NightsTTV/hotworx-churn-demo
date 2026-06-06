output "vpc_id" {
  description = "The ID of the VPC created for HOTWORX deployment"
  value       = aws_vpc.main.id
}

output "ecs_cluster_name" {
  description = "The name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "The name of the ECS Fargate service hosting Streamlit"
  value       = aws_ecs_service.app.name
}

output "rds_endpoint" {
  description = "The endpoint connection string for the database instance"
  value       = aws_db_instance.postgres.endpoint
}

output "secrets_arn" {
  description = "The Amazon Resource Name (ARN) of the Secrets Manager config store"
  value       = aws_secretsmanager_secret.app_secrets.arn
}

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "production"
}

variable "db_username" {
  description = "Database administrator username"
  type        = string
  default     = "hotworx_admin"
}

variable "db_password" {
  description = "Database administrator password"
  type        = string
  sensitive   = true
}

variable "ecs_task_cpu" {
  description = "CPU units for the ECS task definition"
  type        = string
  default     = "512" # 0.5 vCPU
}

variable "ecs_task_memory" {
  description = "Memory (in MiB) for the ECS task definition"
  type        = string
  default     = "1024" # 1 GB
}

variable "app_port" {
  description = "Port exposed by the Streamlit application container"
  type        = number
  default     = 8501
}

variable "image_url" {
  description = "The ECR repository URL and tag for the application container image"
  type        = string
}

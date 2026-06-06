terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ==============================================================================
# VPC & NETWORKING
# ==============================================================================
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "hotworx-churn-vpc-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_subnet" "public_1" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = {
    Name = "hotworx-public-subnet-1"
  }
}

resource "aws_subnet" "public_2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "${var.aws_region}b"
  map_public_ip_on_launch = true

  tags = {
    Name = "hotworx-public-subnet-2"
  }
}

resource "aws_subnet" "private_1" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.10.0/24"
  availability_zone = "${var.aws_region}a"

  tags = {
    Name = "hotworx-private-subnet-1"
  }
}

resource "aws_subnet" "private_2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.11.0/24"
  availability_zone = "${var.aws_region}b"

  tags = {
    Name = "hotworx-private-subnet-2"
  }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "hotworx-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = {
    Name = "hotworx-public-rt"
  }
}

resource "aws_route_table_association" "public_1" {
  subnet_id      = aws_subnet.public_1.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_2" {
  subnet_id      = aws_subnet.public_2.id
  route_table_id = aws_route_table.public.id
}

# ==============================================================================
# SECURITY GROUPS
# ==============================================================================
resource "aws_security_group" "ecs_tasks" {
  name        = "hotworx-ecs-tasks-sg"
  description = "Allow inbound access to Streamlit app port and outbound internet access"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = var.app_port
    to_port     = var.app_port
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "hotworx-ecs-sg"
    Environment = var.environment
  }
}

resource "aws_security_group" "db" {
  name        = "hotworx-db-sg"
  description = "Allow inbound database traffic from ECS container tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "hotworx-db-sg"
    Environment = var.environment
  }
}

# ==============================================================================
# SECRETS MANAGER (PII ENCRYPTION & API CREDENTIALS)
# ==============================================================================
resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "hotworx-churn-app-secrets-${var.environment}"
  description             = "Sensitive parameters and credentials for HOTWORX churn prediction app"
  recovery_window_in_days = 0

  tags = {
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "app_secrets_val" {
  secret_id     = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    HOTWORX_IDENTITY_ENCRYPTION_KEY = "kjBeSXQgvgrZA3O0OJPgJGndaq1PCo8uMWOfPzwy9fA=" # Replace in production
    HOTWORX_IDENTITY_SALT           = "pepper_salt_2026"
    TWILIO_ACCOUNT_SID              = "PLACEHOLDER_TWILIO_SID"
    TWILIO_AUTH_TOKEN               = "PLACEHOLDER_TWILIO_TOKEN"
    TWILIO_FROM_NUMBER              = "+15550001111"
    HW_CAMPAIGN_API_KEY             = "PLACEHOLDER_HW_CAMPAIGN_KEY"
    HW_CAMPAIGN_API_URL             = "https://api.hwcampaign.com/v1/emails"
    PUSH_SERVER_KEY                 = "PLACEHOLDER_FCM_SERVER_KEY"
    FCM_PROJECT_ID                  = "hotworx-churn-demo"
  })
}

# ==============================================================================
# DATABASE (RDS POSTGRESQL FOR LIVE PULLS)
# ==============================================================================
resource "aws_db_subnet_group" "db" {
  name       = "hotworx-db-subnet-group"
  subnet_ids = [aws_subnet.private_1.id, aws_subnet.private_2.id]
}

resource "aws_db_instance" "postgres" {
  identifier             = "hotworx-db-${var.environment}"
  allocated_storage      = 20
  max_allocated_storage  = 100
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t4g.micro"
  db_name                = "hotworx_db"
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.db.name
  vpc_security_group_ids = [aws_security_group.db.id]
  skip_final_snapshot    = true

  tags = {
    Name        = "hotworx-rds-postgres"
    Environment = var.environment
  }
}

# ==============================================================================
# IAM ROLES
# ==============================================================================
resource "aws_iam_role" "ecs_execution" {
  name = "hotworx-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Grant execution role permissions to read secret value from Secrets Manager
resource "aws_iam_policy" "ecs_secrets_access" {
  name        = "hotworx-ecs-secrets-policy"
  description = "Allows ECS tasks to read configuration parameters from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [aws_secretsmanager_secret.app_secrets.arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_secrets_access.arn
}

resource "aws_iam_role" "ecs_task" {
  name = "hotworx-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
      }
    ]
  })
}

# ==============================================================================
# ECS CLUSTER & SERVICE (FARGATE)
# ==============================================================================
resource "aws_ecs_cluster" "main" {
  name = "hotworx-churn-cluster"

  tags = {
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/hotworx-churn-${var.environment}"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "app" {
  family                   = "hotworx-churn-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "hotworx-churn-app"
    image     = var.image_url
    essential = true
    portMappings = [{
      containerPort = var.app_port
      hostPort      = var.app_port
    }]
    environment = [
      { name = "HOTWORX_DATA_SOURCE", value = "production" },
      { name = "HOTWORX_DB_CONN", value = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.endpoint}/${aws_db_instance.postgres.db_name}" },
      { name = "INTERVENTIONS_LIVE", value = "true" }
    ]
    secrets = [
      { name = "HOTWORX_IDENTITY_ENCRYPTION_KEY", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:HOTWORX_IDENTITY_ENCRYPTION_KEY::" },
      { name = "HOTWORX_IDENTITY_SALT", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:HOTWORX_IDENTITY_SALT::" },
      { name = "TWILIO_ACCOUNT_SID", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:TWILIO_ACCOUNT_SID::" },
      { name = "TWILIO_AUTH_TOKEN", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:TWILIO_AUTH_TOKEN::" },
      { name = "TWILIO_FROM_NUMBER", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:TWILIO_FROM_NUMBER::" },
      { name = "HW_CAMPAIGN_API_KEY", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:HW_CAMPAIGN_API_KEY::" },
      { name = "HW_CAMPAIGN_API_URL", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:HW_CAMPAIGN_API_URL::" },
      { name = "PUSH_SERVER_KEY", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:PUSH_SERVER_KEY::" },
      { name = "FCM_PROJECT_ID", valueFrom = "${aws_secretsmanager_secret.app_secrets.arn}:FCM_PROJECT_ID::" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = "hotworx-churn-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = [aws_subnet.public_1.id, aws_subnet.public_2.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

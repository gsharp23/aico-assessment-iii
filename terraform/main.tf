/*
 * Infrastructure for the three-tier stack.
 *
 * Same flat layout as the Assessment II configuration, with three additions the
 * CI/CD pipeline needs: a remote state backend, ECR repositories to push images
 * to, and AWS Secrets Manager to hold the runtime secrets.
 *
 * The EC2 instance does NOT contain the application. It only installs Docker;
 * the deploy workflow ships the compose file and pulls the images from ECR.
 */

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state: the S3 bucket holds the state file, the DynamoDB table holds
  # the lock so a CI run and a laptop can never apply at the same time.
  # Create both once with scripts/bootstrap-state.sh before the first init.
  backend "s3" {
    bucket         = "assessment-iii-tfstate-gsharp23"
    key            = "assessment-iii/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "assessment-iii-tf-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  # Every resource gets these tags, so the whole stack can be found or cleaned
  # up with one console filter.
  default_tags {
    tags = {
      Project = var.project_name
      Managed = "terraform"
    }
  }
}

# ---------------------------------------------------------------- networking

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public-subnet" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project_name}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = { Name = "${var.project_name}-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Only 80 (the app) and 22 (the deploy workflow's SSH) are open. The API and the
# database are NOT exposed - they are reachable only on the Docker network.
resource "aws_security_group" "app" {
  name        = "${var.project_name}-sg"
  description = "Public web access and SSH for deployments"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP - nginx serves the React app here"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH - used by the GitHub Actions deploy job"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-sg" }
}

# ---------------------------------------------------------------- image registry

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "web" {
  name                 = "${var.project_name}-web"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ---------------------------------------------------------------- secrets

# The runtime secrets live here, not in the repo and not in the compose file.
# The EC2 instance reads them at boot using its IAM role.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project_name}/app"
  description             = "Database password and Mem0 API key for the running app"
  recovery_window_in_days = 0 # allows a clean destroy/recreate during the demo
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    POSTGRES_PASSWORD = var.postgres_password
    MEM0_API_KEY      = var.mem0_api_key
  })
}

# ---------------------------------------------------------------- identity

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# Least privilege: invoke Bedrock models, pull from ECR, read this one secret.
resource "aws_iam_role_policy" "ec2" {
  name = "${var.project_name}-ec2-policy"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeBedrockModels"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*" # Bedrock model ARNs vary by region/profile
      },
      {
        Sid    = "PullImagesFromECR"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability"
        ]
        Resource = "*"
      },
      {
        Sid      = "ReadAppSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.app.arn # scoped to this secret only
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ---------------------------------------------------------------- compute

# Look up the current Ubuntu 22.04 AMI instead of pinning an ID that goes stale.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.key_name

  # Only installs Docker. The application arrives via the deploy workflow.
  user_data = templatefile("${path.module}/user_data.sh", {
    aws_region  = var.aws_region
    secret_name = aws_secretsmanager_secret.app.name
  })

  tags = { Name = "${var.project_name}-app" }
}

variable "project_name" {
  description = "Prefix for every resource name and tag"
  type        = string
  default     = "assessment-iii"
}

variable "aws_region" {
  description = "Region for all resources (must have Bedrock model access)"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 size. t3.small - three containers do not fit comfortably in t3.micro."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Existing EC2 key pair name, used by the deploy workflow's SSH step"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Who may SSH in. GitHub-hosted runners have dynamic IPs, so this is open by default."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "postgres_password" {
  description = "Database password. Supplied by CI from a GitHub secret, never committed."
  type        = string
  sensitive   = true
}

variable "mem0_api_key" {
  description = "Mem0 API key. Supplied by CI from a GitHub secret, never committed."
  type        = string
  sensitive   = true
  default     = ""
}

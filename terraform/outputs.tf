# Outputs are how the deploy workflow discovers where to ship the app - nothing
# downstream hardcodes an IP or a registry URL.

output "app_url" {
  description = "Public URL of the running application"
  value       = "http://${aws_instance.app.public_ip}"
}

output "ec2_public_ip" {
  description = "Instance address, used by the deploy job's SSH and smoke-test steps"
  value       = aws_instance.app.public_ip
}

output "ecr_api_url" {
  description = "Repository the backend image is pushed to"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_web_url" {
  description = "Repository the frontend image is pushed to"
  value       = aws_ecr_repository.web.repository_url
}

output "secret_name" {
  description = "Secrets Manager entry the instance reads at boot"
  value       = aws_secretsmanager_secret.app.name
}

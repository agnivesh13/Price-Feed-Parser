locals {
  name_prefix   = var.project_name
  tags = {
    Project   = var.project_name
    Owner     = var.owner_tag
    ManagedBy = "Terraform"
  }
}

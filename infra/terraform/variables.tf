variable "project_name"       { type = string }
variable "aws_region"         { type = string  default = "ap-south-1" }
variable "owner_tag"          { type = string }
variable "fyers_client_id"    { type = string }
variable "fyers_secret_key"   { type = string  sensitive = true }
variable "redirect_url"       { type = string }

# Optional tuning
variable "ingest_schedule_cron" { type = string default = "cron(0/30 3-9 ? * MON-FRI *)" } # every 30m during market window IST

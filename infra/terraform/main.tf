terraform {
  backend "s3" {
    # Optional remote state
    # bucket = "CHANGE_ME-tf-state"
    # key    = "ohlcv/terraform.tfstate"
    # region = "ap-south-1"
  }
}

# Bring files into module dir: CI drops zips beside tf
# Expect oauth_gateway.zip and ingest_history.zip in this folder before apply

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # State stays local by default and is git-ignored. For team use, configure a remote backend
  # (e.g. an Azure Storage account) - see README.md. Never commit terraform.tfstate: it can
  # contain sensitive values.
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

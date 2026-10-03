variable "subscription_id" {
  description = "Azure subscription ID to deploy into."
  type        = string
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "retail-data-platform"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.project))
    error_message = "Use 3-40 lowercase letters, digits or hyphens."
  }
}

variable "location" {
  description = "Azure region, e.g. westeurope, eastus."
  type        = string
  default     = "westeurope"
}

variable "vm_size" {
  description = <<-EOT
    VM size. Measured footprint of the full stack (PostgreSQL, Airflow api-server/scheduler/
    dag-processor, dashboard, Caddy) is ~1.3 GB RAM idle, ~2.5 GB while dbt runs, plus ~2 GB
    for on-VM image builds. Standard_B2s (2 vCPU / 4 GB + swap) is the minimum;
    Standard_B2ms (2 vCPU / 8 GB) is comfortable and leaves room for Grafana.
  EOT
  type        = string
  default     = "Standard_B2ms"
}

variable "os_disk_size_gb" {
  description = "OS disk size. Images (~6 GB) + PostgreSQL data + backups."
  type        = number
  default     = 64
}

variable "admin_username" {
  description = "Linux admin / deploy user created on the VM."
  type        = string
  default     = "deploy"
}

variable "ssh_public_key" {
  description = "SSH public key (contents, not a path) allowed to log in. Password login is disabled."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Source CIDRs allowed to reach SSH (22). Restrict to your own IP, e.g. [\"203.0.113.4/32\"]."
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0 && !contains(var.ssh_allowed_cidrs, "0.0.0.0/0")
    error_message = "Provide at least one CIDR and do not open SSH to the whole internet."
  }
}

variable "dns_label" {
  description = "Optional Azure DNS label: <label>.<region>.cloudapp.azure.com. Leave empty to skip."
  type        = string
  default     = ""
}

variable "repository_url" {
  description = "Git URL cloned onto the VM by cloud-init."
  type        = string
  default     = "https://github.com/lugonesnicolas/retail-data-platform.git"
}

variable "tags" {
  description = "Extra tags applied to every resource."
  type        = map(string)
  default     = {}
}

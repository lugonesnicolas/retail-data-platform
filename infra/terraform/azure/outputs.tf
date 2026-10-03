output "public_ip" {
  description = "Static public IP - point DOMAIN and airflow.DOMAIN A records here."
  value       = azurerm_public_ip.this.ip_address
}

output "fqdn" {
  description = "Azure-provided DNS name (only when dns_label is set)."
  value       = azurerm_public_ip.this.fqdn
}

output "ssh_command" {
  description = "SSH into the VM."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.this.ip_address}"
}

output "app_dir" {
  description = "Where cloud-init cloned the repository (DEPLOY_PATH for GitHub Actions)."
  value       = "/opt/retail-data-platform"
}

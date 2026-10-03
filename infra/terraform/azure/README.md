# Azure infrastructure (Terraform)

> **Warning:** applying this configuration creates **billable** Azure resources (VM, managed
> disk, static public IP). Run `terraform destroy` when you no longer need them.

Provisions only what the single-VM deployment needs:

- resource group, VNet `10.20.0.0/16`, subnet `10.20.1.0/24`
- network security group: SSH (22) only from `ssh_allowed_cidrs`, HTTP/HTTPS from the internet;
  everything else (including PostgreSQL) denied
- static Standard public IP (optional Azure DNS label)
- Ubuntu 24.04 LTS VM (`Standard_B2ms` by default), SSH-key authentication only, StandardSSD
  OS disk, managed boot diagnostics
- cloud-init: Docker Engine + Compose plugin, ufw, 2 GB swap, repository cloned to
  `/opt/retail-data-platform`

```bash
cp terraform.tfvars.example terraform.tfvars    # never commit this file
az login
terraform init
terraform plan -out tfplan
terraform apply tfplan
terraform output
```

Then follow [docs/cloud-deployment.md](../../../docs/cloud-deployment.md#dns-and-first-deployment).

**State.** The state is local and git-ignored, and it may contain sensitive data. For team use,
configure an `azurerm` remote backend (Storage Account + container) with state locking.

| Variable | Default | Description |
|---|---|---|
| `subscription_id` | – | Azure subscription |
| `ssh_public_key` | – | Public key contents for the admin user |
| `ssh_allowed_cidrs` | – | CIDRs allowed to SSH (`0.0.0.0/0` is rejected) |
| `location` | `westeurope` | Region |
| `vm_size` | `Standard_B2ms` | `Standard_B2s` is the minimum (disable Grafana) |
| `os_disk_size_gb` | `64` | |
| `admin_username` | `deploy` | Also the `DEPLOY_USER` GitHub secret |
| `dns_label` | `""` | Optional `<label>.<region>.cloudapp.azure.com` |
| `repository_url` | this repo | Cloned by cloud-init |

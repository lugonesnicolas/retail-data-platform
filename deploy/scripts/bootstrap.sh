#!/usr/bin/env bash
# One-time (idempotent) preparation of a fresh Ubuntu 22.04/24.04 VM. Run with sudo:
#   sudo DEPLOY_USER=deploy REPO_URL=https://github.com/<you>/retail-data-platform.git \
#        bash deploy/scripts/bootstrap.sh
# Azure VMs created by infra/terraform/azure already ran the equivalent cloud-init.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-deploy}}"
APP_DIR="${APP_DIR:-/opt/retail-data-platform}"
REPO_URL="${REPO_URL:-https://github.com/lugonesnicolas/retail-data-platform.git}"

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 1; }

apt-get update -y
apt-get install -y ca-certificates curl git ufw unattended-upgrades

if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck disable=SC1091
    codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
if [[ ! -f /etc/docker/daemon.json ]]; then
    echo '{"log-driver": "json-file", "log-opts": {"max-size": "20m", "max-file": "5"}}' \
        > /etc/docker/daemon.json
fi
systemctl enable --now docker
systemctl restart docker

id -u "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"

# Firewall: only SSH, HTTP and HTTPS. PostgreSQL is never published by the prod compose file.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

if ! swapon --show | grep -q /swapfile; then
    [[ -f /swapfile ]] || { fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile; }
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "Bootstrap complete. Next, as $DEPLOY_USER:"
echo "  cd $APP_DIR && scripts/generate-env.sh && \$EDITOR .env   # set DOMAIN, ACME_EMAIL"
echo "  deploy/scripts/deploy.sh"

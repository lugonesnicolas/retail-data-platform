#!/usr/bin/env bash
# Create .env from .env.example with freshly generated secrets.
# Idempotent: an existing .env is never overwritten.
set -euo pipefail

target="${1:-.env}"
if [[ -f "$target" ]]; then
    echo "$target already exists - leaving it untouched."
    exit 0
fi

rand_hex() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }
fernet() { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }

cp .env.example "$target"
chmod 600 "$target"
tmp="$(mktemp)"
while IFS= read -r line; do
    case "$line" in
        *=CHANGE_ME_FERNET) printf '%s=%s\n' "${line%%=*}" "$(fernet)" ;;
        *=CHANGE_ME) printf '%s=%s\n' "${line%%=*}" "$(rand_hex)" ;;
        *) printf '%s\n' "$line" ;;
    esac
done < "$target" > "$tmp"
mv "$tmp" "$target"
chmod 600 "$target"
echo "Created $target with generated secrets (Airflow admin password: see AIRFLOW_ADMIN_PASSWORD)."

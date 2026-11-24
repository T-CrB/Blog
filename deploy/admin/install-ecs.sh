#!/usr/bin/env bash
set +x
set -euo pipefail

if [[ $(id -u) != 0 ]]; then
    echo 'Run as root on the ECS (sudo bash install-ecs.sh).' >&2
    exit 1
fi

src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app=/opt/tcrb-blog-admin
etc=/etc/tcrb-blog-admin
config=$etc/admin.conf
credential=$etc/github-client-secret

install -d -m 0755 -- "$app"
if ! python3 -m venv "$app/venv"; then
    echo 'Install python3-venv and run this installer again.' >&2
    exit 1
fi
"$app/venv/bin/python" -m pip --disable-pip-version-check install \
    --require-hashes --only-binary=:all: -r "$src/requirements.txt"
install -d -m 0700 -- "$etc"
if [[ ! -e "$config" && ! -e "$credential" ]]; then
    IFS= read -r -p 'GitHub OAuth Client ID: ' client_id
    IFS= read -r -s -p 'GitHub OAuth Client Secret (hidden): ' client_secret
    printf '\n'
    if [[ ! "$client_id" =~ ^[A-Za-z0-9_-]{8,128}$ || ! "$client_secret" =~ ^[A-Za-z0-9_-]{8,256}$ ]]; then
        echo 'Client ID or secret is invalid. Use the dedicated GitHub OAuth App values.' >&2
        exit 1
    fi
    (
        umask 077
        printf 'ADMIN_ORIGIN=https://47.110.252.64\nGITHUB_OWNER_ID=224936987\nGITHUB_CLIENT_ID=%s\n' "$client_id" > "$config"
        printf '%s\n' "$client_secret" > "$credential"
    )
    unset client_secret
elif [[ ! -s "$config" || ! -s "$credential" ]]; then
    echo 'The existing OAuth config or secret is missing. Check /etc/tcrb-blog-admin before reinstalling.' >&2
    exit 1
fi

install -m 0644 -- "$src/admin_service.py" "$src/article_editor.py" "$src/github_editor.py" "$app/"
install -m 0644 -- "$src/tcrb-blog-admin.service" /etc/systemd/system/tcrb-blog-admin.service
systemctl daemon-reload
systemctl enable tcrb-blog-admin.service
systemctl restart tcrb-blog-admin.service

printf '\nInstalled the local admin service. Nginx and blog deployment were not changed.\n'
printf 'Check journalctl -u tcrb-blog-admin.service -n 20 --no-pager before adding the HTTPS proxy.\n'

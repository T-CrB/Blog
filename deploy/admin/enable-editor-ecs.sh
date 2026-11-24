#!/usr/bin/env bash
set +x
set -euo pipefail

if [[ $(id -u) != 0 || $# != 1 ]]; then
    echo 'Usage on ECS: sudo bash enable-editor-ecs.sh /root/blog-editor.private-key.pem' >&2
    exit 1
fi
if [[ ! -f /opt/tcrb-blog-admin/article_editor.py || ! -f /opt/tcrb-blog-admin/github_editor.py ]]; then
    echo 'Upgrade the admin service with install-ecs.sh first.' >&2
    exit 1
fi
deploy=/usr/local/lib/tcrb-web-deploy
if [[ ! -f "$deploy/provenance.py" ]] || ! systemctl is-enabled --quiet tcrb-web-deploy.timer ||
    ! systemctl is-active --quiet tcrb-web-deploy.timer ||
    ! runuser -u blogdeploy -- /usr/bin/python3 -B "$deploy/pull.py" --verify-current; then
    echo 'Upgrade the production puller and deploy a verified build before enabling the editor.' >&2
    exit 1
fi
if [[ ! -x /usr/bin/openssl ]] || ! /usr/bin/openssl rsa -in "$1" -passin pass: -check -noout >/dev/null 2>&1; then
    echo 'Use the RSA private key file downloaded for the dedicated GitHub App.' >&2
    exit 1
fi

IFS= read -r -p 'GitHub App Client ID (not the existing OAuth App): ' client_id
IFS= read -r -p 'GitHub App installation ID: ' installation
if [[ ! "$client_id" =~ ^[A-Za-z0-9._-]{1,128}$ || ! "$installation" =~ ^[1-9][0-9]{0,19}$ ]]; then
    echo 'Invalid GitHub App Client ID or installation ID.' >&2
    exit 1
fi

umask 077
etc=/etc/tcrb-blog-admin
drop=/etc/systemd/system/tcrb-blog-admin.service.d
install -d -m 0700 -- "$etc"
install -d -m 0755 -- "$drop"
install -m 0600 -- "$1" "$etc/github-editor-key.pem"
printf 'GITHUB_EDITOR_CLIENT_ID=%s\nGITHUB_EDITOR_INSTALLATION_ID=%s\n' "$client_id" "$installation" > "$etc/editor.conf"
cat > "$drop/editor.conf" <<'EOF'
[Service]
EnvironmentFile=/etc/tcrb-blog-admin/editor.conf
LoadCredential=github-editor-key:/etc/tcrb-blog-admin/github-editor-key.pem
EOF
systemctl daemon-reload
systemctl restart tcrb-blog-admin.service
printf '\nArticle editor configured. No changes were made to Nginx, the identity OAuth App, or site deployment.\n'

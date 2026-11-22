#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" != 0 ]]; then
  echo 'Run this script as root (or with sudo) from the verified ECS setup bundle.' >&2
  exit 1
fi
for cmd in curl python3 systemctl runuser; do
  command -v "$cmd" >/dev/null || { echo "Please install $cmd first." >&2; exit 1; }
done

cd -- "$(dirname -- "$0")"
site=/var/www/tcrb-web-deploy
app=/usr/local/lib/tcrb-web-deploy
for path in "$site" "$site/releases" "$app"; do
  if [[ -L "$path" ]]; then
    echo "Refusing to install through a symlink: $path" >&2
    exit 1
  fi
done
if [[ -e "$site/current" && ! -L "$site/current" ]]; then
  echo 'Refusing to replace an existing current directory or file.' >&2
  exit 1
fi

if ! id blogdeploy >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin blogdeploy
fi
install -d -m 0755 -o root -g root "$app"
install -m 0644 -o root -g root site_release.py pull.py "$app/"
install -d -m 0755 -o blogdeploy -g "$(id -gn blogdeploy)" "$site"
runuser -u blogdeploy -- install -d -m 0755 "$site/releases"
install -m 0644 -o root -g root tcrb-web-deploy.service tcrb-web-deploy.timer /etc/systemd/system/
systemctl daemon-reload
printf '%s\n' 'Installed without changing your web server.' \
  'Start tcrb-web-deploy.service to test it before switching Nginx and enabling the timer.'

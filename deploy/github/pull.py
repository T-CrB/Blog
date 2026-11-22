"""Fetch only the public GitHub Release assets this static site needs."""

import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import BadZipFile

from site_release import (
    ARCHIVE_NAME, MANIFEST_NAME, MAX_MANIFEST_BYTES, TARGET_PATTERN,
    activate_site, live_target, matches_site, read_manifest,
)

RELEASES = "https://github.com/T-CrB/Blog/releases"
SITE_ROOT = Path("/var/www/tcrb-web-deploy")
STATE_ROOT = Path("/var/lib/tcrb-web-deploy")


def download(url, destination, limit):
    subprocess.run([
        "curl", "--disable", "--fail", "--silent", "--show-error", "--location",
        "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "5",
        "--connect-timeout", "8", "--max-time", "35", "--max-filesize", str(limit),
        "--output", str(destination), url,
    ], check=True, timeout=40)


def pull(site_root, state):
    current = live_target(site_root)
    with tempfile.TemporaryDirectory(prefix="pull-", dir=state) as scratch:
        work = Path(scratch)
        index = work / MANIFEST_NAME
        download(f"{RELEASES}/latest/download/{MANIFEST_NAME}", index, MAX_MANIFEST_BYTES)
        manifest = read_manifest(index)
        if current is not None:
            sequence = int(TARGET_PATTERN.fullmatch(current.as_posix()).group(1))
            if manifest.sequence < sequence:
                print(f"Ignoring older release {manifest.revision}")
                return
            if manifest.sequence == sequence and current != manifest.target:
                raise ValueError("A different build already uses this deployment sequence")
            release = site_root / current
            if current == manifest.target and not release.is_symlink() and matches_site(release, manifest.revision):
                return

        # Pin the ZIP to the exact tag from the manifest. "Latest" can move between requests.
        archive = work / ARCHIVE_NAME
        download(f"{RELEASES}/download/{manifest.tag}/{ARCHIVE_NAME}", archive, manifest.size)
        activate_site(archive, site_root, manifest)
        print(f"Live Astro revision: {manifest.revision}")


if __name__ == "__main__":
    try:
        pull(SITE_ROOT, STATE_ROOT)
    except (OSError, ValueError, KeyError, BadZipFile, subprocess.SubprocessError) as error:
        sys.exit(f"Deployment failed; current site was not changed: {error}")

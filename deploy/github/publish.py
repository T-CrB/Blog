"""Make a checked build visible only after all assets have uploaded to a draft Release."""

import json
import os
import subprocess
import sys
from pathlib import Path

from site_release import ARCHIVE_NAME, MANIFEST_NAME, SETUP_NAME, check_archive, read_manifest, sha256_file

ASSET_NAMES = (ARCHIVE_NAME, MANIFEST_NAME, SETUP_NAME)


def release_command(repository, *args, **kwargs):
    return subprocess.run(["gh", "release", *args, "--repo", repository], text=True, timeout=180, **kwargs)


def main_head(repository):
    return subprocess.check_output([
        "gh", "api", "--hostname", "github.com", f"repos/{repository}/git/ref/heads/main", "--jq", ".object.sha",
    ], text=True, timeout=30).strip()


def existing_release(repository, tag):
    result = release_command(repository, "view", tag, "--json", "isDraft,isPrerelease,targetCommitish,assets",
                             capture_output=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if result.stderr.strip() == "release not found":
        return None
    raise RuntimeError(f"Cannot check for an existing Release: {result.stderr.strip()}")


def publish(repository, revision, sequence, bundle):
    if main_head(repository) != revision:
        print("Skipping publication: this commit is no longer the head of main.")
        return
    manifest = read_manifest(bundle / MANIFEST_NAME)
    if (manifest.revision, manifest.sequence) != (revision, sequence):
        raise ValueError("Build artifact does not belong to this workflow run")
    check_archive(bundle / ARCHIVE_NAME, manifest)
    setup_digest = sha256_file(bundle / SETUP_NAME)
    title = f"Blog production · {revision[:12]}"
    notes = (f"Static site built from `main` at `{revision}`.\n\n"
             f"ECS setup SHA-256: `{setup_digest}`")

    release = existing_release(repository, manifest.tag)
    if release is not None:
        if release["targetCommitish"] != revision or release["isPrerelease"]:
            raise ValueError("Existing Release does not match this production commit")
        if not release["isDraft"]:
            uploaded = {asset["name"] for asset in release["assets"] if asset["state"] == "uploaded"}
            if not set(ASSET_NAMES) <= uploaded:
                raise ValueError("Existing published Release is missing production assets")
            print(f"Release {manifest.tag} is already published.")
            return
    else:
        release_command(repository, "create", manifest.tag, "--draft", "--target", revision,
                        "--title", title, "--notes", notes, check=True)

    # A failed upload leaves only a draft. A retry can replace incomplete draft assets.
    release_command(repository, "upload", manifest.tag, *(str(bundle / name) for name in ASSET_NAMES),
                    "--clobber", check=True)
    if main_head(repository) != revision:
        print("Leaving the draft unpublished: main advanced while its assets uploaded.")
        return
    release_command(repository, "edit", manifest.tag, "--draft=false", "--latest", "--notes", notes, check=True)


if __name__ == "__main__":
    try:
        publish(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"], int(os.environ["GITHUB_RUN_NUMBER"]),
                Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f"Release publication failed: {error}")

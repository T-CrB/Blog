"""Verify Release assets against the protected production workflow, not Release metadata."""

import os
import subprocess

from site_release import MANIFEST_NAME, SETUP_NAME

REPOSITORY = "T-CrB/Blog"
SOURCE_REF = "refs/heads/main"
SIGNER = f"https://github.com/{REPOSITORY}/.github/workflows/ci-cd.yml@{SOURCE_REF}"
MANIFEST_PROOF = f"{MANIFEST_NAME}.sigstore.jsonl"
SETUP_PROOF = f"{SETUP_NAME}.sigstore.jsonl"
MAX_PROOF_BYTES = 256 * 1024


def verify(subject, proof, revision, state):
    if not 0 < proof.stat().st_size <= MAX_PROOF_BYTES:
        raise ValueError("Invalid production attestation size")
    env = {
        **os.environ,
        "GH_CONFIG_DIR": str(state / "gh-config"),
        "XDG_CACHE_HOME": str(state / "cache"),
        "GH_PROMPT_DISABLED": "1",
        "GH_NO_UPDATE_NOTIFIER": "1",
    }
    # Verification has a local bundle and must not send any GitHub credential.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        env.pop(name, None)
    subprocess.run([
        "gh", "attestation", "verify", str(subject), "--bundle", str(proof),
        "--repo", REPOSITORY, "--cert-identity", SIGNER, "--source-ref", SOURCE_REF,
        "--source-digest", revision, "--deny-self-hosted-runners",
    ], env=env, check=True, timeout=55)

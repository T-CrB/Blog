"""Package a static Astro build and switch to a fully checked copy on ECS."""

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

ARCHIVE_NAME = "tcrb-blog-site.zip"
MANIFEST_NAME = "tcrb-blog-deploy.json"
SETUP_NAME = "tcrb-blog-ecs-setup.tar.gz"
TAG_PREFIX = "tcrb-blog-"
REQUIRED_PAGES = ("index.html", "blog/index.html")
REVISION_FILE = "_deploy-revision.txt"
MAX_MANIFEST_BYTES = 1024
MAX_ARCHIVE_BYTES = 64 * 1024**2
MAX_UNPACKED_BYTES = 256 * 1024**2
TARGET_PATTERN = re.compile(r"releases/([1-9][0-9]{0,15})-[0-9a-f]{64}")


@dataclass(frozen=True)
class Manifest:
    revision: str
    sequence: int
    size: int
    sha256: str

    def __post_init__(self):
        if not isinstance(self.revision, str) or not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise ValueError("Expected a full Git commit SHA")
        if type(self.sequence) is not int or not 1 <= self.sequence < 10**16:
            raise ValueError("Invalid deployment sequence")
        if type(self.size) is not int or not 1 <= self.size <= MAX_ARCHIVE_BYTES:
            raise ValueError("Invalid archive size (limit: 64 MiB)")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Invalid archive SHA-256")

    @property
    def tag(self):
        return TAG_PREFIX + self.revision

    @property
    def target(self):
        return Path("releases") / f"{self.sequence}-{self.sha256}"


def read_manifest(path):
    with path.open("rb") as source:
        contents = source.read(MAX_MANIFEST_BYTES + 1)
    if len(contents) > MAX_MANIFEST_BYTES:
        raise ValueError("Release manifest exceeds the size limit")
    data = json.loads(contents)
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported release manifest")
    return Manifest(**{key: data[key] for key in ("revision", "sequence", "size", "sha256")})


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def check_archive(archive, manifest):
    if archive.stat().st_size != manifest.size or sha256_file(archive) != manifest.sha256:
        raise ValueError("Archive size or SHA-256 does not match the release manifest")


def has_pages(folder):
    return all((folder / name).is_file() and (folder / name).stat().st_size for name in REQUIRED_PAGES)


def matches_site(folder, revision):
    if not has_pages(folder) or not (folder / REVISION_FILE).is_file():
        return False
    with (folder / REVISION_FILE).open("rb") as marker:
        return marker.read(42) == (revision + "\n").encode("ascii")


def make_bundle(source, output, revision, sequence):
    if not has_pages(source):
        raise ValueError("Build must contain the homepage and blog index")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE_NAME
    total = 41  # The revision marker is also in the ZIP.
    with ZipFile(archive, "w", ZIP_DEFLATED) as package:
        for path in sorted(source.rglob("*")):
            name = path.relative_to(source).as_posix()
            if path.is_symlink() or name == REVISION_FILE:
                raise ValueError(f"Unexpected build output: {name}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError(f"Build output is not a regular file: {name}")
            total += path.stat().st_size
            if total > MAX_UNPACKED_BYTES:
                raise ValueError("Unpacked site exceeds the 256 MiB limit")
            package.write(path, name)
        package.writestr(REVISION_FILE, revision + "\n")
    manifest = Manifest(revision, sequence, archive.stat().st_size, sha256_file(archive))
    (output / MANIFEST_NAME).write_text(json.dumps({"version": 1, **asdict(manifest)}) + "\n", encoding="ascii")
    return manifest


def unpack_site(archive, destination, revision):
    with ZipFile(archive) as package:
        names = set()
        total = 0
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            entry_type = stat.S_IFMT(entry.external_attr >> 16)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or ":" in entry.filename or not path.parts or entry.orig_filename != path.as_posix()
                    or entry_type not in (0, stat.S_IFREG) or path in names):
                raise ValueError(f"Unexpected archive entry: {entry.orig_filename!r}")
            names.add(path)
            total += entry.file_size
            if total > MAX_UNPACKED_BYTES:
                raise ValueError("Unpacked site exceeds the 256 MiB limit")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    if not matches_site(destination, revision):
        raise ValueError("Archive is missing the expected pages or revision marker")


def live_target(site_root):
    releases = site_root / "releases"
    if site_root.is_symlink() or releases.is_symlink() or not releases.is_dir():
        raise ValueError("Site and releases paths must be ordinary directories")
    current = site_root / "current"
    if not current.is_symlink():
        if current.exists():
            raise ValueError("Refusing to replace an existing current directory or file")
        return None
    target = Path(os.readlink(current))
    if not TARGET_PATTERN.fullmatch(target.as_posix()):
        raise ValueError("Current site link does not point at a managed release")
    return target


def activate_site(archive, site_root, manifest):
    live_target(site_root)
    check_archive(archive, manifest)
    release = site_root / manifest.target
    if release.is_symlink() or (release.exists() and not matches_site(release, manifest.revision)):
        raise ValueError("Existing release directory is unexpected or damaged")

    with tempfile.TemporaryDirectory(prefix=".stage-", dir=site_root / "releases") as scratch:
        stage = Path(scratch)
        if not release.exists():
            extracted = stage / "site"
            extracted.mkdir(mode=0o755)
            unpack_site(archive, extracted, manifest.revision)
            extracted.rename(release)
        link = stage / "current"
        link.symlink_to(manifest.target, target_is_directory=True)
        link.replace(site_root / "current")  # Same filesystem; no partially served release.


if __name__ == "__main__":
    source, output, revision, sequence = sys.argv[1:]
    make_bundle(Path(source), Path(output), revision, int(sequence))

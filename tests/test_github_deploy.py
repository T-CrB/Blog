"""Deployment tests use local archives and mock GitHub traffic only."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "github"))
import publish
import pull
from site_release import (
    ARCHIVE_NAME, MANIFEST_NAME, REQUIRED_PAGES, REVISION_FILE, SETUP_NAME,
    activate_site, check_archive, make_bundle, read_manifest, unpack_site,
)


class DeployTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.dist = self.root / "dist"
        self.site = self.root / "site"
        self.state = self.root / "state"
        for folder in (self.dist / "blog", self.site / "releases", self.state):
            folder.mkdir(parents=True)
        self.write_pages("Initial")
        self.revision = "a" * 40
        self.repo = "example/blog"
        self.bundle = self.root / "build"
        self.manifest = self.make_bundle(self.bundle, self.revision, 7)

    def write_pages(self, text):
        for name in REQUIRED_PAGES:
            (self.dist / name).write_text(f"{text}: {name}", encoding="ascii")

    def make_bundle(self, folder, revision, sequence):
        manifest = make_bundle(self.dist, folder, revision, sequence)
        (folder / SETUP_NAME).write_bytes(b"setup package fixture")
        return manifest

    def fetch_from(self, bundle):
        def download(url, destination, limit):
            source = bundle / url.rsplit("/", 1)[-1]
            self.assertLessEqual(source.stat().st_size, limit)
            shutil.copyfile(source, destination)
        return download

    def require_symlinks(self):
        try:
            (self.root / "probe").symlink_to(self.site, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            if os.name != "nt":
                raise
            self.skipTest(f"Windows does not allow symlink creation for this account: {error}")

    def test_round_trip(self):
        archive = self.bundle / ARCHIVE_NAME
        manifest = read_manifest(self.bundle / MANIFEST_NAME)
        self.assertEqual(manifest, self.manifest)
        check_archive(archive, manifest)
        output = self.root / "unpacked"
        unpack_site(archive, output, self.revision)
        self.assertEqual((output / "index.html").read_text(), "Initial: index.html")
        self.assertEqual((output / REVISION_FILE).read_text().strip(), self.revision)

    def test_rejects_wrong_size_or_hash(self):
        archive = self.bundle / ARCHIVE_NAME
        contents = archive.read_bytes()
        for updated in (contents + b"x", bytes([contents[0] ^ 1]) + contents[1:]):
            with self.subTest(size=len(updated)):
                archive.write_bytes(updated)
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    check_archive(archive, self.manifest)

    def test_manifest_rejects_bad_types_and_untrusted_revision(self):
        path = self.bundle / MANIFEST_NAME
        data = json.loads(path.read_text())
        for invalid in ({"sequence": True}, {"size": 10**10}, {"revision": "../fake"}, {"version": True}):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps({**data, **invalid}), encoding="ascii")
                with self.assertRaises(ValueError):
                    read_manifest(path)

    def test_rejects_unsafe_zip_paths_and_symlinks(self):
        link = ZipInfo("symlink")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.root / "invalid.zip"
        for entry in ("../escape", "/outside.html", r"dir\bad", "nested/../file", "name:stream", link):
            with self.subTest(entry=entry):
                with ZipFile(archive, "w") as package:
                    package.writestr("dir/bad" if entry == r"dir\bad" else entry, "invalid")
                if entry == r"dir\bad":
                    # Windows' ZIP writer normalizes backslashes; put the raw name in the headers.
                    archive.write_bytes(archive.read_bytes().replace(b"dir/bad", b"dir\\bad"))
                with self.assertRaisesRegex(ValueError, "Unexpected archive entry"):
                    unpack_site(archive, self.root / "unpacked", self.revision)
        self.assertFalse((self.root / "escape").exists())

    def test_rejects_incomplete_pages_and_mismatched_commit(self):
        with self.assertRaisesRegex(ValueError, "revision marker"):
            unpack_site(self.bundle / ARCHIVE_NAME, self.root / "unpacked", "b" * 40)
        (self.dist / "blog/index.html").unlink()
        with self.assertRaisesRegex(ValueError, "blog index"):
            make_bundle(self.dist, self.root / "broken", self.revision, 8)

    def test_does_not_replace_existing_current_directory(self):
        current = self.site / "current"
        current.mkdir()
        with self.assertRaisesRegex(ValueError, "existing current"):
            activate_site(self.bundle / ARCHIVE_NAME, self.site, self.manifest)
        self.assertTrue(current.is_dir())
        self.assertFalse(current.is_symlink())

    def test_release_switches_atomically_and_skips_same_or_older_build(self):
        self.require_symlinks()
        current = self.site / "current"
        with patch.object(pull, "download", side_effect=self.fetch_from(self.bundle)) as fetch:
            pull.pull(self.site, self.state)
            self.assertEqual(fetch.call_args_list[1].args[0],
                             f"{pull.RELEASES}/download/{self.manifest.tag}/{ARCHIVE_NAME}")
            self.assertEqual(current.resolve(), (self.site / self.manifest.target).resolve())
            fetch.reset_mock()
            pull.pull(self.site, self.state)
            self.assertEqual(fetch.call_count, 1)
        self.write_pages("Updated")
        new_bundle = self.root / "second"
        new_manifest = self.make_bundle(new_bundle, "b" * 40, 8)
        with patch.object(pull, "download", side_effect=self.fetch_from(new_bundle)):
            pull.pull(self.site, self.state)
        self.assertEqual(current.resolve(), (self.site / new_manifest.target).resolve())
        with patch.object(pull, "download", side_effect=self.fetch_from(self.bundle)) as fetch:
            pull.pull(self.site, self.state)
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual((current / "index.html").read_text(), "Updated: index.html")
        self.assertTrue((self.site / self.manifest.target / "index.html").is_file())

    def test_bad_download_leaves_the_live_site_in_place(self):
        self.require_symlinks()
        activate_site(self.bundle / ARCHIVE_NAME, self.site, self.manifest)
        current = self.site / "current"
        live = current.resolve()
        bad_bundle = self.root / "bad"
        self.make_bundle(bad_bundle, "b" * 40, 8)
        (bad_bundle / ARCHIVE_NAME).write_bytes(b"truncated")
        with patch.object(pull, "download", side_effect=self.fetch_from(bad_bundle)):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                pull.pull(self.site, self.state)
        with patch.object(pull, "download", side_effect=subprocess.CalledProcessError(28, "curl")):
            with self.assertRaises(subprocess.CalledProcessError):
                pull.pull(self.site, self.state)
        self.assertEqual(current.resolve(), live)

    def test_old_job_does_not_publish(self):
        with patch.object(publish, "main_head", return_value="b" * 40), \
                patch.object(publish, "release_command") as release:
            publish.publish(self.repo, self.revision, 7, self.bundle)
        release.assert_not_called()

    def test_publish_after_all_assets_are_uploaded(self):
        with patch.object(publish, "main_head", return_value=self.revision), \
                patch.object(publish, "existing_release", return_value=None), \
                patch.object(publish, "release_command") as release:
            publish.publish(self.repo, self.revision, 7, self.bundle)
        self.assertEqual([call.args[1] for call in release.call_args_list], ["create", "upload", "edit"])
        self.assertIn("--draft", release.call_args_list[0].args)
        self.assertIn(str(self.bundle / ARCHIVE_NAME), release.call_args_list[1].args)
        self.assertIn(str(self.bundle / MANIFEST_NAME), release.call_args_list[1].args)
        self.assertIn(str(self.bundle / SETUP_NAME), release.call_args_list[1].args)
        self.assertIn("--latest", release.call_args_list[2].args)

    def test_main_can_advance_during_asset_upload(self):
        draft = {"targetCommitish": self.revision, "isDraft": True, "isPrerelease": False}
        with patch.object(publish, "main_head", side_effect=[self.revision, "b" * 40]), \
                patch.object(publish, "existing_release", return_value=draft), \
                patch.object(publish, "release_command") as release:
            publish.publish(self.repo, self.revision, 7, self.bundle)
        self.assertEqual([call.args[1] for call in release.call_args_list], ["upload"])
        self.assertIn("--clobber", release.call_args.args)

    def test_failed_upload_does_not_publish_the_draft(self):
        with patch.object(publish, "main_head", return_value=self.revision), \
                patch.object(publish, "existing_release", return_value=None), \
                patch.object(publish, "release_command", side_effect=[None, subprocess.CalledProcessError(1, "gh")]) as release:
            with self.assertRaises(subprocess.CalledProcessError):
                publish.publish(self.repo, self.revision, 7, self.bundle)
        self.assertEqual([call.args[1] for call in release.call_args_list], ["create", "upload"])

    def test_existing_published_release_is_not_overwritten(self):
        existing = {"targetCommitish": self.revision, "isDraft": False, "isPrerelease": False,
                    "assets": [{"name": name, "state": "uploaded"} for name in publish.ASSET_NAMES]}
        with patch.object(publish, "main_head", return_value=self.revision), \
                patch.object(publish, "existing_release", return_value=existing), \
                patch.object(publish, "release_command") as release:
            publish.publish(self.repo, self.revision, 7, self.bundle)
        release.assert_not_called()


if __name__ == "__main__":
    unittest.main()

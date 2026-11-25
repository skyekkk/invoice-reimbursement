"""使用临时本地Git仓库测试，不触碰安装目录、真实网络或报销数据。"""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("sync_skill", Path(__file__).resolve().parents[1] / "scripts/sync_skill.py")
sync_skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_skill)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote.git"
        self.author = self.base / "author"
        self.client = self.base / "client"
        self.backups = self.base / "backups"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--initial-branch=main")
        self.author.mkdir()
        git(self.author, "init", "--initial-branch=main")
        self.identify(self.author)
        (self.author / "SKILL.md").write_text("version one\n", encoding="utf-8")
        (self.author / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        git(self.author, "add", "SKILL.md", "VERSION")
        git(self.author, "commit", "-m", "initial")
        git(self.author, "remote", "add", "origin", str(self.remote))
        git(self.author, "push", "origin", "main")
        subprocess.run(["git", "clone", str(self.remote), str(self.client)], check=True, capture_output=True)
        self.identify(self.client)
        git(self.client, "config", "--local", "skill.trustedOrigin", str(self.remote))

    def identify(self, root):
        git(root, "config", "user.name", "Skill Test")
        git(root, "config", "user.email", "skill-test@example.invalid")

    def publish(self):
        (self.author / "SKILL.md").write_text("version two\n", encoding="utf-8")
        (self.author / "VERSION").write_text("2.0.0\n", encoding="utf-8")
        git(self.author, "add", "SKILL.md", "VERSION")
        git(self.author, "commit", "-m", "update")
        git(self.author, "push", "origin", "main")

    def sync(self, **kwargs):
        return sync_skill.sync(self.client, expected=str(self.remote), backup_root=self.backups, **kwargs)

    def test_current_checks_remote_without_backup(self):
        response = self.sync()
        self.assertEqual(response["status"], "current")
        self.assertFalse(self.backups.exists())
        self.assertEqual(response["latest"], git(self.author, "rev-parse", "HEAD"))

    def test_update_preserves_backup_and_external_profile(self):
        profile = self.base / "profile.json"
        profile.write_text('{"name":"local only"}', encoding="utf-8")
        self.publish()
        response = self.sync()
        self.assertEqual(response["status"], "updated")
        self.assertEqual((self.client / "SKILL.md").read_text(), "version two\n")
        self.assertEqual((Path(response["backup"]) / "SKILL.md").read_text(), "version one\n")
        self.assertFalse((Path(response["backup"]) / ".git").exists())
        self.assertEqual(profile.read_text(), '{"name":"local only"}')
        self.assertEqual(self.sync()["status"], "current")

    def test_check_only_does_not_update(self):
        self.publish()
        response = self.sync(check_only=True)
        self.assertEqual(response["status"], "update-available")
        self.assertEqual((self.client / "SKILL.md").read_text(), "version one\n")
        self.assertFalse(self.backups.exists())

    def test_local_modified_file_is_preserved(self):
        self.publish()
        (self.client / "SKILL.md").write_text("personal edits\n", encoding="utf-8")
        self.assertEqual(self.sync()["status"], "blocked")
        self.assertEqual((self.client / "SKILL.md").read_text(), "personal edits\n")

    def test_untracked_file_is_preserved(self):
        self.publish()
        (self.client / "custom.txt").write_text("keep me", encoding="utf-8")
        self.assertEqual(self.sync()["status"], "blocked")
        self.assertEqual((self.client / "custom.txt").read_text(), "keep me")
        self.assertEqual((self.client / "VERSION").read_text(), "1.0.0\n")

    def test_wrong_source_is_blocked_before_fetch(self):
        git(self.client, "remote", "set-url", "origin", "https://example.invalid/wrong.git")
        self.assertEqual(self.sync()["status"], "blocked")

    def test_missing_binding_is_blocked(self):
        git(self.client, "config", "--unset", "skill.trustedOrigin")
        self.assertEqual(self.sync()["status"], "blocked")

    def test_wrong_branch_is_blocked(self):
        git(self.client, "checkout", "-b", "custom")
        self.assertEqual(self.sync()["status"], "blocked")

    def test_local_commits_diverging_are_not_discarded(self):
        self.publish()
        (self.client / "local.txt").write_text("local commit", encoding="utf-8")
        git(self.client, "add", "local.txt")
        git(self.client, "commit", "-m", "local")
        before = git(self.client, "rev-parse", "HEAD")
        self.assertEqual(self.sync()["status"], "blocked")
        self.assertEqual(git(self.client, "rev-parse", "HEAD"), before)

    def test_rewritten_remote_history_is_not_accepted(self):
        git(self.author, "checkout", "--orphan", "new-history")
        git(self.author, "commit", "-m", "new root")
        git(self.author, "push", "--force", "origin", "HEAD:main")
        self.assertEqual(self.sync()["status"], "blocked")

    def test_network_failure_does_not_change_files(self):
        before = git(self.client, "rev-parse", "HEAD")
        unavailable = str(self.base / "missing.git")
        git(self.client, "remote", "set-url", "origin", unavailable)
        git(self.client, "config", "skill.trustedOrigin", unavailable)
        with self.assertRaises(sync_skill.SyncError):
            sync_skill.sync(self.client, expected=unavailable, backup_root=self.backups)
        self.assertEqual(git(self.client, "rev-parse", "HEAD"), before)
        self.assertEqual((self.client / "SKILL.md").read_text(), "version one\n")

    def test_downloaded_copy_without_git_is_not_managed(self):
        copied = self.base / "zip-copy"
        copied.mkdir()
        (copied / "SKILL.md").write_text("keep", encoding="utf-8")
        self.assertEqual(sync_skill.sync(copied)["status"], "not-managed")
        self.assertEqual((copied / "SKILL.md").read_text(), "keep")

    def test_symlink_in_new_version_is_blocked(self):
        if os.name == "nt":
            self.skipTest("Windows创建符号链接可能需要开发者权限")
        (self.author / "link").symlink_to("SKILL.md")
        git(self.author, "add", "link")
        git(self.author, "commit", "-m", "symlink")
        git(self.author, "push", "origin", "main")
        self.assertEqual(self.sync()["status"], "blocked")
        self.assertFalse((self.client / "link").exists())

    def test_backup_inside_skill_is_rejected(self):
        self.publish()
        response = sync_skill.sync(self.client, expected=str(self.remote), backup_root=self.client / "backups")
        self.assertEqual(response["status"], "blocked")
        self.assertEqual((self.client / "VERSION").read_text(), "1.0.0\n")

    def test_post_merge_hook_is_not_run(self):
        self.publish()
        marker = self.base / "hook-ran"
        hook = self.client / ".git/hooks/post-merge"
        hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n', encoding="utf-8")
        hook.chmod(0o755)
        self.assertEqual(self.sync()["status"], "updated")
        self.assertFalse(marker.exists())

    def test_fetch_hook_is_not_run_even_when_only_checking(self):
        self.publish()
        marker = self.base / "fetch-hook-ran"
        hook = self.client / ".git/hooks/reference-transaction"
        hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n', encoding="utf-8")
        hook.chmod(0o755)
        self.assertEqual(self.sync(check_only=True)["status"], "update-available")
        self.assertFalse(marker.exists())

    def test_ignored_local_file_cannot_be_overwritten(self):
        (self.author / ".gitignore").write_text("private.json\n", encoding="utf-8")
        git(self.author, "add", ".gitignore")
        git(self.author, "commit", "-m", "ignore local profile")
        git(self.author, "push", "origin", "main")
        self.assertEqual(self.sync()["status"], "updated")
        local_file = self.client / "private.json"
        local_file.write_text("LOCAL", encoding="utf-8")
        (self.author / "private.json").write_text("REMOTE", encoding="utf-8")
        git(self.author, "add", "-f", "private.json")
        git(self.author, "commit", "-m", "incoming path conflict")
        git(self.author, "push", "origin", "main")
        self.assertEqual(self.sync()["status"], "blocked")
        self.assertEqual(local_file.read_text(), "LOCAL")


if __name__ == "__main__":
    unittest.main()

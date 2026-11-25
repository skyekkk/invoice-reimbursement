#!/usr/bin/env python3
"""每次启动检查GitHub，备份后仅快进同步；不覆盖使用者本地修改。"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ORIGIN = "https://github.com/skyekkk/invoice-reimbursement.git"
BRANCH = "main"
SUCCESS = {"current", "updated", "update-available"}


class SyncError(Exception):
    pass


def run_git(root, *args):
    # fetch也可能触发本地reference-transaction钩子，所有Git调用统一关闭。
    with tempfile.TemporaryDirectory(prefix="invoice-skill-hooks-") as hooks:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + hooks, "-c", "submodule.recurse=false", "-C", str(root), *args],
            capture_output=True, text=True, timeout=40,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
        )


def git(root, *args):
    """不回显Git错误细节，避免带有认证信息的地址进入日志。"""
    response = run_git(root, *args)
    if response.returncode:
        raise SyncError("Git操作未完成。")
    return response.stdout.strip()


def result(status, message, **values):
    return dict(status=status, message=message, **values)


def default_backup_root():
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "invoice-reimbursement/backups"


def sync(root, expected=ORIGIN, backup_root=None, check_only=False):
    root = Path(root).resolve()
    backup_root = Path(backup_root or default_backup_root()).expanduser().resolve()
    if not (root / ".git").is_dir():
        return result("not-managed", "这不是独立Git安装。请按README安装；当前文件未改动。")
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        return result("blocked", "技能目录不是独立仓库，未更新。")
    trusted = git(root, "config", "--local", "--get", "--default", "", "skill.trustedOrigin")
    if trusted != expected or git(root, "remote", "get-url", "origin") != expected:
        return result("blocked", "安装来源未绑定或与指定GitHub仓库不一致，未更新。")
    if git(root, "symbolic-ref", "--short", "HEAD") != BRANCH:
        return result("blocked", "当前不是main分支，已保留原状。")

    before = git(root, "rev-parse", "HEAD")
    # 不用origin/main，避免只下载压缩包或过期引用造成假“最新”。
    git(root, "fetch", "--no-tags", "--no-recurse-submodules", "origin", BRANCH)
    latest = git(root, "rev-parse", "FETCH_HEAD")
    common = dict(commit=before, latest=latest)
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        return result("blocked", "已检查远端，但本地有修改或未跟踪文件；保留全部内容，未覆盖。", **common)
    if before == latest:
        return result("current", "已联网检查，当前已是最新版。", **common)

    ancestry = run_git(root, "merge-base", "--is-ancestor", before, latest)
    if ancestry.returncode != 0:
        return result("blocked", "本地与远端分叉或远端历史已改写，未强制覆盖。", **common)
    # 防止误配的远端把符号链接或子模块装入技能路径。
    tree = git(root, "ls-tree", "-r", latest)
    if any(line.split(" ", 1)[0] in {"120000", "160000"} for line in tree.splitlines()):
        return result("blocked", "新版含符号链接或子模块，需要维护者核对；未更新。", **common)
    ignored = set(filter(None, git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split("\0")))
    incoming = set(filter(None, git(root, "ls-tree", "-r", "-z", "--name-only", latest).split("\0")))
    if any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in ignored for b in incoming):
        return result("blocked", "新版路径与本地被忽略文件冲突，保留本地内容，未覆盖。", **common)
    if check_only:
        return result("update-available", "发现新版；只检查模式未修改技能。", **common)
    if backup_root == root or root in backup_root.parents:
        return result("blocked", "备份位置不能在技能目录内，未更新。", **common)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_root / (stamp + "-" + before[:12])
    backup_root.mkdir(parents=True, exist_ok=True)
    # 仓库干净时备份全部工作文件；.git历史仍由原仓库保留。
    shutil.copytree(root, backup, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
    (backup / "BACKUP-INFO.json").write_text(
        json.dumps({"origin": expected, "commit": before, "next_commit": latest}, indent=2) + "\n",
        encoding="utf-8",
    )
    # 不覆盖被忽略文件，不自动stash，不执行钩子，不运行新版程序。
    git(root, "merge", "--ff-only", "--no-overwrite-ignore", "--no-autostash", latest)
    after = git(root, "rev-parse", "HEAD")
    if after != latest or git(root, "status", "--porcelain", "--untracked-files=all"):
        return result("blocked", "更新后状态不符合预期，请核对备份与工作目录后再做业务。", backup=str(backup), **common)
    version_file = root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else None
    return result("updated", "已备份并同步新版。请立即重新读取SKILL.md及本次所需参考文件。",
                  previous=before, commit=after, backup=str(backup), version=version)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="只查远端，不更新文件")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if (root / ".skill-install.json").exists():
        from github_snapshot import main as snapshot_main
        return snapshot_main(["--check-only"] if args.check_only else [])
    try:
        response = sync(root, check_only=args.check_only)
    except (OSError, SyncError, subprocess.TimeoutExpired):
        response = result("unavailable", "未能完成GitHub检查或同步。请检查Git、网络和目录权限；不要把当前版称为已更新。")
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response["status"] in SUCCESS else 2


if __name__ == "__main__":
    sys.exit(main())

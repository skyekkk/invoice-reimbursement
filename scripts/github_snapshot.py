#!/usr/bin/env python3
"""通过GitHub官方API安装/更新，适用于Git主站连接不通的环境。"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO = "skyekkk/invoice-reimbursement"
ORIGIN = "https://github.com/" + REPO
API = "https://api.github.com/repos/" + REPO
STATE = ".skill-install.json"
REQUIRED = {"SKILL.md", "VERSION", "README.md", "scripts/sync_skill.py", "scripts/github_snapshot.py",
            "references/profile.md", "assets/报销单-空白.xlsx", "config/profile.example.json", "agents/openai.yaml",
            "scripts/qq_mail.py", "references/qq-mail.md"}
MAX_BYTES = 20 * 1024 * 1024


class SnapshotError(Exception):
    pass


def response(status, message, **values):
    return dict(status=status, message=message, **values)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def linked_inside(path, root):
    for current in (path, *path.parents):
        if current.is_symlink():
            return True
        if current == root:
            break
    return False


def safe_path(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(p in ("", ".", "..") or ":" in p for p in name.split("/")):
        raise SnapshotError("下载包包含不安全路径。")
    if path.parts[0] in {".git", STATE}:
        raise SnapshotError("下载包包含保留路径。")
    return name


def read_url(url, limit=MAX_BYTES):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "invoice-reimbursement-skill"})
    with urllib.request.urlopen(request, timeout=25) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SnapshotError("下载超过技能包大小上限。")
    return data


def read_json(url):
    return json.loads(read_url(url).decode("utf-8"))


def latest_info():
    info = read_json(API + "/commits/main")
    commit = info["sha"]
    tree = info["commit"]["tree"]["sha"]
    if not all(re.fullmatch(r"[a-f0-9]{40}", x) for x in (commit, tree)):
        raise SnapshotError("GitHub提交信息不完整。")
    return commit, tree


def download_snapshot(commit, tree):
    listing = read_json(API + "/git/trees/" + tree + "?recursive=1")
    if listing.get("truncated"):
        raise SnapshotError("远端文件列表被截断。")
    blobs = {}
    for entry in listing["tree"]:
        if entry["type"] == "tree":
            continue
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise SnapshotError("不接受符号链接或子模块。")
        blobs[safe_path(entry["path"])] = entry["sha"]
    if len(blobs) > 200 or not REQUIRED.issubset(blobs):
        raise SnapshotError("新版技能文件不完整或超出预期大小。")
    raw = read_url(API + "/zipball/" + commit)
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        total = 0
        for item in archive.infolist():
            if item.is_dir():
                continue
            parts = item.filename.split("/", 1)
            if len(parts) != 2:
                raise SnapshotError("下载包结构异常。")
            name = safe_path(parts[1])
            if name in files or name not in blobs or stat.S_ISLNK(item.external_attr >> 16):
                raise SnapshotError("下载文件与远端树不符。")
            total += item.file_size
            if total > MAX_BYTES:
                raise SnapshotError("解压文件超出大小上限。")
            data = archive.read(item)
            git_hash = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if git_hash != blobs[name]:
                raise SnapshotError("下载文件校验不一致。")
            files[name] = data
    if set(files) != set(blobs):
        raise SnapshotError("下载文件有遗漏。")
    if "name: invoice-reimbursement" not in files["SKILL.md"].decode("utf-8"):
        raise SnapshotError("技能入口身份不符。")
    return files


def write_files(root, files, commit):
    for name, data in files.items():
        path = root / safe_path(name)
        if linked_inside(path, root):
            raise SnapshotError("目标路径存在符号链接。")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    state = {"origin": ORIGIN, "commit": commit, "files": {name: digest(data) for name, data in files.items()}}
    (root / STATE).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install(target):
    target = Path(target).expanduser().absolute()
    if target.exists() or target.is_symlink():
        return response("blocked", "同名目录已存在，保留原状。请先比较并备份，再指定空目录安装。")
    commit, tree = latest_info()
    files = download_snapshot(commit, tree)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".invoice-install-", dir=str(target.parent)) as work:
        stage = Path(work) / "stage"
        stage.mkdir()
        write_files(stage, files, commit)
        os.rename(stage, target)
    return response("installed", "完整技能已安装，接下来运行sync_skill.py检查并读取SKILL.md。",
                    commit=commit, path=str(target))


def default_backup_root():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "invoice-reimbursement/backups"


def sync_snapshot(root, check_only=False, backup_root=None):
    root = Path(root).absolute()
    state_path = root / STATE
    if root.is_symlink() or state_path.is_symlink() or not state_path.is_file():
        return response("not-managed", "缺少可信安装记录，请按README使用完整安装方式。")
    root = root.resolve()
    state_path = root / STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("origin") != ORIGIN or not re.fullmatch(r"[a-f0-9]{40}", state.get("commit", "")):
        return response("blocked", "更新来源绑定异常，未更新。")
    baseline = state.get("files", {})
    if not isinstance(baseline, dict) or not REQUIRED.issubset(baseline):
        return response("blocked", "安装记录不完整，未更新。")
    before = state["commit"]
    latest, tree = latest_info()
    for name, expected_hash in baseline.items():
        path = root / safe_path(name)
        if linked_inside(path, root) or not path.is_file() or digest(path.read_bytes()) != expected_hash:
            return response("blocked", "已检查远端，但本地技能文件有改动或缺失；保留原状，未覆盖。", commit=before, latest=latest)
    if before == latest:
        return response("current", "已通过GitHub官方接口联网检查，当前已是最新版。", commit=before)
    compare = read_json(API + "/compare/" + before + "..." + latest)
    if compare.get("status") != "ahead":
        return response("blocked", "远端历史不是当前版本的后续，停止覆盖。", commit=before, latest=latest)
    if check_only:
        return response("update-available", "发现新版；只检查模式未修改技能。", commit=before, latest=latest)
    files = download_snapshot(latest, tree)
    for name in files:
        path = root / safe_path(name)
        if name not in baseline and (path.exists() or path.is_symlink()):
            return response("blocked", "新版路径与本地自有文件冲突，保留本地内容，未覆盖。")
        for parent in path.parents:
            if parent == root:
                break
            if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
                return response("blocked", "新版路径与本地文件或链接冲突，未更新。")
    backup_root = Path(backup_root or default_backup_root()).expanduser().resolve()
    if backup_root == root or root in backup_root.parents:
        return response("blocked", "备份位置不能位于技能目录内。")
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_root / (stamp + "-" + before[:12])
    shutil.copytree(root, backup, symlinks=True)
    work = Path(tempfile.mkdtemp(prefix=".invoice-update-", dir=str(root.parent)))
    preserve_work = False
    try:
        stage = work / "stage"
        shutil.copytree(root, stage, symlinks=True)
        # 只替换上次安装管理的文件，未知本地文件保留，配置始终在外部。
        for name in baseline:
            (stage / name).unlink()
        write_files(stage, files, latest)
        old = work / "previous"
        os.rename(root, old)
        try:
            os.rename(stage, root)
        except OSError:
            try:
                os.rename(old, root)
            except OSError:
                preserve_work = True
                return response("unavailable", "新版替换和旧版恢复均未完成；旧目录与备份已保留，请先恢复再继续。",
                                recovery=str(old), backup=str(backup), path=str(root))
            raise
    finally:
        if not preserve_work:
            shutil.rmtree(work)
    return response("updated", "已备份并更新。请立即重新读取SKILL.md及所需参考文件。",
                    previous=before, commit=latest, backup=str(backup), version=files["VERSION"].decode().strip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", metavar="TARGET", help="安装到不存在的新目录")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = install(args.install) if args.install else sync_snapshot(Path(__file__).resolve().parents[1], args.check_only)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, SnapshotError):
        value = response("unavailable", "未能完成GitHub检查或更新。请检查网络及目录权限，不要把当前版称为已更新。")
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value["status"] in {"installed", "current", "updated", "update-available"} else 2


if __name__ == "__main__":
    sys.exit(main())

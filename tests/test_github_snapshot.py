import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("github_snapshot", Path(__file__).resolve().parents[1] / "scripts/github_snapshot.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "skill"
        self.root.mkdir()
        self.before = "a" * 40
        self.after = "b" * 40
        self.files = {name: b"first\n" for name in m.REQUIRED}
        self.files['SKILL.md'] = b"---\nname: invoice-reimbursement\n---\n"
        self.files['VERSION'] = b"1.0.0\n"
        m.write_files(self.root, self.files, self.before)
        self.new = dict(self.files, VERSION=b"2.0.0\n")

    def sync(self, *, latest=None, files=None, status="ahead", **kwargs):
        with patch.object(m, 'latest_info', return_value=(latest or self.after, 'c' * 40)), \
             patch.object(m, 'read_json', return_value={'status': status}), \
             patch.object(m, 'download_snapshot', return_value=files or self.new):
            return m.sync_snapshot(self.root, backup_root=self.base / 'backups', **kwargs)

    def test_current(self):
        self.assertEqual(self.sync(latest=self.before)['status'], 'current')

    def test_installs_complete_verified_files_into_empty_target(self):
        target = self.base / 'new-skill'
        with patch.object(m, 'latest_info', return_value=(self.after, 'c'*40)), \
             patch.object(m, 'download_snapshot', return_value=self.new):
            self.assertEqual(m.install(target)['status'], 'installed')
        self.assertEqual((target/'VERSION').read_bytes(), b'2.0.0\n')
        self.assertTrue((target/m.STATE).exists())

    def test_installer_will_not_overwrite_existing(self):
        self.assertEqual(m.install(self.root)['status'], 'blocked')

    def test_update_backs_up_preserves_unmanaged_files(self):
        (self.root/'private.txt').write_text('mine')
        result=self.sync()
        self.assertEqual(result['status'],'updated')
        self.assertEqual((self.root/'VERSION').read_bytes(), b'2.0.0\n')
        self.assertEqual((Path(result['backup'])/'VERSION').read_bytes(),b'1.0.0\n')
        self.assertEqual((self.root/'private.txt').read_text(),'mine')
        self.assertEqual(json.loads((self.root/m.STATE).read_text())['commit'],self.after)

    def test_local_edit_blocks_without_loss(self):
        (self.root/'VERSION').write_text('LOCAL')
        self.assertEqual(self.sync()['status'],'blocked')
        self.assertEqual((self.root/'VERSION').read_text(),'LOCAL')

    def test_new_remote_path_conflict_blocks(self):
        (self.root/'private.txt').write_text('LOCAL')
        files=dict(self.new, **{'private.txt':b'REMOTE'})
        self.assertEqual(self.sync(files=files)['status'],'blocked')
        self.assertEqual((self.root/'private.txt').read_text(),'LOCAL')

    def test_different_origin_and_rewritten_history_block(self):
        self.assertEqual(self.sync(status='diverged')['status'],'blocked')
        s=json.loads((self.root/m.STATE).read_text());s['origin']='https://example.invalid'
        (self.root/m.STATE).write_text(json.dumps(s))
        self.assertEqual(self.sync()['status'],'blocked')

    def test_check_only_leaves_files(self):
        self.assertEqual(self.sync(check_only=True)['status'],'update-available')
        self.assertEqual((self.root/'VERSION').read_bytes(),b'1.0.0\n')
        self.assertFalse((self.base/'backups').exists())

    def test_network_failure_leaves_files(self):
        with patch.object(m,'latest_info',side_effect=OSError('network unavailable')):
            with self.assertRaises(OSError):m.sync_snapshot(self.root)
        self.assertEqual((self.root/'VERSION').read_bytes(),b'1.0.0\n')

    def test_archive_rejects_traversal(self):
        tree={'truncated':False,'tree':[{'path':n,'type':'blob','mode':'100644','sha':'0'*40} for n in m.REQUIRED]}
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('repo/../outside','bad')
        with patch.object(m,'read_json',return_value=tree),patch.object(m,'read_url',return_value=raw.getvalue()):
            with self.assertRaises(m.SnapshotError):m.download_snapshot(self.after,'c'*40)
        self.assertFalse((self.base/'outside').exists())

    def test_archive_checks_every_git_blob_hash(self):
        import hashlib
        tree={'truncated':False,'tree':[]}
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            for name,data in self.new.items():
                z.writestr('repo/'+name,data)
                sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                tree['tree'].append({'path':name,'type':'blob','mode':'100644','sha':sha})
        with patch.object(m,'read_json',return_value=tree),patch.object(m,'read_url',return_value=raw.getvalue()):
            self.assertEqual(m.download_snapshot(self.after,'c'*40),self.new)
            tree['tree'][0]['sha']='0'*40
            with self.assertRaises(m.SnapshotError):m.download_snapshot(self.after,'c'*40)

    def test_swap_failure_restores_original(self):
        real_rename=m.os.rename
        def fail_stage(src,dst):
            if Path(src).name=='stage' and Path(dst)==self.root:raise OSError('simulated rename failure')
            return real_rename(src,dst)
        with patch.object(m.os,'rename',side_effect=fail_stage):
            with self.assertRaises(OSError):self.sync()
        self.assertEqual((self.root/'VERSION').read_bytes(),b'1.0.0\n')


if __name__=='__main__':unittest.main()

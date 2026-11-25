import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("qq_mail", Path(__file__).resolve().parents[1] / "scripts/qq_mail.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "profile/qq-mail.json"
        self.config_patch = patch.object(m, "CONFIG", self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def run_main(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = m.main(args)
        return result, output.getvalue()

    def test_tls_readonly_and_logout_without_fetch(self):
        connection = Mock()
        connection.select.return_value = ("OK", [])
        with patch.object(m.imaplib, "IMAP4_SSL", return_value=connection) as constructor:
            m.verify("example@qq.com", "test-value")
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.args, ("imap.qq.com", 993))
        self.assertTrue(constructor.call_args.kwargs["ssl_context"].check_hostname)
        connection.select.assert_called_once_with("INBOX", readonly=True)
        connection.logout.assert_called_once()
        connection.fetch.assert_not_called()
        connection.store.assert_not_called()

    def test_login_error_does_not_reveal_server_or_secret(self):
        connection = Mock()
        connection.login.side_effect = m.imaplib.IMAP4.error("private-test-value")
        with patch.object(m.imaplib, "IMAP4_SSL", return_value=connection):
            with self.assertRaises(RuntimeError) as error:
                m.verify("example@qq.com", "private-test-value")
        self.assertNotIn("private-test-value", str(error.exception))
        connection.logout.assert_called_once()

    def test_unpaired_check_does_not_prompt(self):
        with patch.object(m, "prompt") as prompt, patch.object(m, "keychain") as keychain:
            result, _ = self.run_main(["--check"])
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        keychain.assert_not_called()

    def test_paired_check_reuses_keychain_without_config_mutation(self):
        m.save_settings("example@qq.com")
        before = self.config.read_bytes()
        connection = Mock()
        connection.select.return_value = ("OK", [])
        with patch.object(m, "keychain", return_value="test-value") as keychain, \
             patch.object(m.imaplib, "IMAP4_SSL", return_value=connection), patch.object(m, "prompt") as prompt:
            result, output = self.run_main(["--check"])
        self.assertEqual(result, 0)
        self.assertNotIn("test-value", output)
        keychain.assert_called_once_with("example@qq.com")
        prompt.assert_not_called()
        connection.select.assert_called_once_with("INBOX", readonly=True)
        self.assertEqual(self.config.read_bytes(), before)

    def test_setup_saves_only_after_verified_and_secret_stays_outside_json(self):
        code = "A" * 16
        order = []
        with patch.object(m.sys, "platform", "darwin"), \
             patch.object(m, "prompt", side_effect=["example@qq.com", code]), \
             patch.object(m, "verify", side_effect=lambda *a: order.append("verify")), \
             patch.object(m, "keychain", side_effect=lambda *a: order.append("keychain")):
            result, output = self.run_main(["--setup"])
        self.assertEqual(result, 0)
        self.assertEqual(order, ["verify", "keychain"])
        self.assertNotIn(code, self.config.read_text() + output)
        self.assertEqual(json.loads(self.config.read_text())["account"], "example@qq.com")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_failed_verification_does_not_persist_credential(self):
        with patch.object(m.sys, "platform", "darwin"), \
             patch.object(m, "prompt", side_effect=["example@qq.com", "A" * 16]), \
             patch.object(m, "verify", side_effect=RuntimeError("验证失败")), \
             patch.object(m, "keychain") as keychain:
            result, _ = self.run_main(["--setup"])
        self.assertEqual(result, 2)
        keychain.assert_not_called()
        self.assertFalse(self.config.exists())

    def test_cancel_does_not_overwrite_existing_pair(self):
        m.save_settings("example@qq.com")
        before = self.config.read_bytes()
        with patch.object(m.sys, "platform", "darwin"), \
             patch.object(m, "prompt", side_effect=RuntimeError("已取消")), \
             patch.object(m, "keychain") as keychain:
            result, _ = self.run_main(["--setup"])
        self.assertEqual(result, 2)
        self.assertEqual(self.config.read_bytes(), before)
        keychain.assert_not_called()

    def test_other_os_does_not_open_prompt_or_store_plaintext(self):
        with patch.object(m.sys, "platform", "linux"), patch.object(m, "prompt") as prompt:
            result, _ = self.run_main(["--setup"])
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        self.assertFalse(self.config.exists())

    def test_symlink_settings_cannot_overwrite_another_file(self):
        self.config.parent.mkdir()
        other = Path(self.temp.name) / "other"
        other.write_text("keep")
        self.config.symlink_to(other)
        with self.assertRaises(RuntimeError):
            m.save_settings("example@qq.com")
        self.assertEqual(other.read_text(), "keep")

    def test_network_error_does_not_echo_exception_details(self):
        m.save_settings("example@qq.com")
        with patch.object(m, "keychain", side_effect=OSError("private-test-value")):
            result, output = self.run_main(["--check"])
        self.assertEqual(result, 2)
        self.assertNotIn("private-test-value", output)

    def test_invalid_configuration_shape_returns_failure_without_traceback(self):
        self.config.parent.mkdir()
        self.config.write_text("[]")
        result, output = self.run_main(["--check"])
        self.assertEqual(result, 2)
        self.assertIn("配置格式无效", output)

    def test_aborted_connection_does_not_request_new_authorization_code(self):
        connection = Mock()
        connection.login.side_effect = m.imaplib.IMAP4.abort("private-test-value")
        with patch.object(m.imaplib, "IMAP4_SSL", return_value=connection):
            with self.assertRaises(RuntimeError) as error:
                m.verify("example@qq.com", "private-test-value")
        self.assertIn("无需因此重新生成授权码", str(error.exception))
        self.assertNotIn("private-test-value", str(error.exception))


if __name__ == "__main__":
    unittest.main()

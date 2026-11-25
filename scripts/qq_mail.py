#!/usr/bin/env python3
"""本机QQ邮箱连接；授权码仅从安全窗口接收并存入系统钥匙串。"""
import argparse
import ctypes
import imaplib
import json
import os
import sys
from contextlib import contextmanager
import re
import ssl
import subprocess
from pathlib import Path

SERVICE = b"invoice-reimbursement.qq-imap"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "invoice-reimbursement/qq-mail.json"


def native_libraries():
    if sys.platform != "darwin":
        raise RuntimeError("此安全配对工具目前支持macOS；其他系统请按邮箱指南使用网页登录或已授权连接器。")
    security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    security.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    return security, core


def prompt(message, hidden=False):
    script = 'text returned of (display dialog ' + json.dumps(message, ensure_ascii=False) + ' default answer ""'
    if hidden:
        script += ' with hidden answer'
    script += ' buttons {"取消", "继续"} default button "继续" with title "QQ邮箱安全连接")'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("输入已取消；尚未完成连接。")
    return result.stdout.strip()


def keychain(account, secret=None):
    SEC, CF = native_libraries()
    account = account.encode()
    length, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
    status = SEC.SecKeychainFindGenericPassword(None, len(SERVICE), SERVICE, len(account), account,
                                               ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
    try:
        if secret is None:
            if status:
                raise RuntimeError("未能从钥匙串取得授权；请先运行安全连接。")
            return ctypes.string_at(data, length.value).decode()
        if status == -25300:
            status = SEC.SecKeychainAddGenericPassword(None, len(SERVICE), SERVICE, len(account), account,
                                                       len(secret), secret, None)
        elif status == 0:
            status = SEC.SecKeychainItemModifyAttributesAndData(item, None, len(secret), secret)
        if status:
            raise RuntimeError("未能保存到系统钥匙串；没有写入其他文件。")
    finally:
        if data.value:
            SEC.SecKeychainItemFreeContent(None, data)
        if item.value:
            CF.CFRelease(item)


@contextmanager
def readonly_connection(account, secret):
    connection = None
    try:
        connection = imaplib.IMAP4_SSL("imap.qq.com", 993, ssl_context=ssl.create_default_context(), timeout=25)
        connection.login(account, secret)
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("收件箱只读访问未通过；未完成连接验证。")
        yield connection
    except imaplib.IMAP4.abort:
        raise RuntimeError("邮箱连接中断，请检查网络后重试，无需因此重新生成授权码。") from None
    except imaplib.IMAP4.error:
        raise RuntimeError("QQ邮箱验证未通过；请核对邮箱地址、授权码及IMAP服务是否开启。") from None
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass


def verify(account, secret):
    with readonly_connection(account, secret):
        pass


def valid_account(account):
    return isinstance(account, str) and re.fullmatch(r"[^\s@]+@(qq\.com|foxmail\.com)", account, re.IGNORECASE)


def read_settings():
    if not CONFIG.is_file():
        raise RuntimeError("尚未配对QQ邮箱；请按邮箱指南运行 --setup。")
    if CONFIG.is_symlink():
        raise RuntimeError("邮箱配置不能是符号链接，未读取。")
    settings = json.loads(CONFIG.read_text())
    if not isinstance(settings, dict):
        raise RuntimeError("邮箱配置格式无效，请按邮箱指南修复或重新配对。")
    if not valid_account(settings.get("account")):
        raise RuntimeError("邮箱配置中的账号无效，请重新配对。")
    return settings


@contextmanager
def paired_connection():
    """供授权后的邮件检索调用；保持EXAMINE并使用BODY.PEEK，不打印凭据。"""
    settings = read_settings()
    secret = keychain(settings["account"])
    try:
        with readonly_connection(settings["account"], secret) as connection:
            yield connection
    finally:
        del secret


def save_settings(account):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG.is_symlink():
        raise RuntimeError("邮箱配置不能是符号链接，未保存。")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(CONFIG), flags, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"account": account, "host": "imap.qq.com", "port": 993,
                   "credential_store": "macOS Keychain", "keychain_service": SERVICE.decode(),
                   "scope": "read-only client operations"}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    CONFIG.chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="检查现有配对，不索取授权码")
    mode.add_argument("--setup", action="store_true", help="用本机隐藏窗口首次配对或更换账号")
    args = parser.parse_args(argv)
    try:
        if not args.setup:
            with paired_connection():
                pass
            print("连接检查通过：已验证收件箱只读访问，未读取邮件正文或附件。")
            return 0
        if sys.platform != "darwin":
            raise RuntimeError("此安全配对工具目前支持macOS；其他系统请使用网页登录或已授权连接器。")
        if CONFIG.is_symlink():
            raise RuntimeError("邮箱配置不能是符号链接，未修改。")
        if CONFIG.exists():
            prompt("已存在邮箱配对。继续会重新验证并更新本机邮箱配置；要保留现有配对请点取消。可直接点继续。")
        account = prompt("请输入你的完整QQ邮箱地址，例如：数字@qq.com。这里不填授权码。")
        if not valid_account(account):
            raise RuntimeError("邮箱地址格式未通过；没有保存或连接。")
        code = prompt("请输入本次新生成的QQ邮箱授权码，输入将隐藏。不要输入QQ密码或曾发到聊天中的授权码。", hidden=True)
        if not re.fullmatch(r"[A-Za-z]{16}", code):
            raise RuntimeError("授权码格式未通过；没有保存或连接。")
        try:
            verify(account, code)
            keychain(account, code.encode())
        finally:
            del code
        save_settings(account)
        print("连接成功：收件箱只读访问已验证，授权码已存入本机钥匙串。未下载邮件或附件。")
        return 0
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        if isinstance(error, RuntimeError):
            print(str(error))
        else:
            print("连接未完成；请检查网络、系统钥匙串权限及本机配置。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

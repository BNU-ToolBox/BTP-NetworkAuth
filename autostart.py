"""Windows 11 autostart entry for campus-network authentication."""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.dont_write_bytecode = True

PLUGIN_ID = "campus-network-auth"
THIS_DIR = Path(__file__).resolve().parent
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "BNU-ToolBox-CampusNetworkAuth"
HOST_ROOT: Path | None = None
PLUGIN_DATA_PATH: Path | None = None


def _require_windows_11() -> None:
    if sys.platform != "win32":
        raise RuntimeError("BNU-ToolBox currently supports Windows 11 only")
    if sys.getwindowsversion().build < 22000:
        raise RuntimeError("BNU-ToolBox currently supports Windows 11 only")


def _python_command() -> str:
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    if windowless.is_file():
        return str(windowless)
    return str(executable)


def _launch_command() -> list[str]:
    if HOST_ROOT is None or PLUGIN_DATA_PATH is None:
        raise RuntimeError("缺少主程序目录或插件数据目录")
    return [
        _python_command(),
        str(THIS_DIR / "autostart.py"),
        "--run",
        "--home",
        str(HOST_ROOT),
        "--data-dir",
        str(PLUGIN_DATA_PATH),
    ]


def _configure_paths(home: str = "", data_dir: str = "") -> None:
    global HOST_ROOT, PLUGIN_DATA_PATH
    home_value = home or os.environ.get("BNU_TOOLBOX_HOME", "")
    if home_value:
        HOST_ROOT = Path(home_value).expanduser().resolve()
        if str(HOST_ROOT) not in sys.path:
            sys.path.insert(0, str(HOST_ROOT))
    data_value = data_dir or os.environ.get("BNU_TOOLBOX_PLUGIN_DATA_DIR", "")
    if data_value:
        PLUGIN_DATA_PATH = Path(data_value).expanduser().resolve()
    elif PLUGIN_DATA_PATH is None:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            PLUGIN_DATA_PATH = Path(local) / "BNU-ToolBox" / "plugins" / PLUGIN_ID


def install() -> dict:
    _require_windows_11()
    import winreg

    command = subprocess.list2cmdline(_launch_command())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        winreg.SetValueEx(
            key, REGISTRY_VALUE, 0, winreg.REG_SZ, command)
    return {
        "installed": True,
        "method": "registry-run",
        "command": command,
    }


def uninstall() -> dict:
    _require_windows_11()
    import winreg

    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, REGISTRY_VALUE)
    except FileNotFoundError:
        pass
    return {"installed": False, "method": "registry-run"}


def status() -> dict:
    if sys.platform != "win32":
        return {"installed": False, "method": "unsupported"}
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, REGISTRY_VALUE)
        return {
            "installed": True,
            "method": "registry-run",
            "command": value,
        }
    except FileNotFoundError:
        return {"installed": False, "method": "registry-run"}


def apply_enabled(enabled: bool) -> dict:
    return install() if enabled else uninstall()


class _InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        if self.handle.read(1) == b"":
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError(
                "已有校园网认证自启进程在运行") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.handle is None:
            return
        try:
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()


def _load_config() -> dict:
    if HOST_ROOT is None:
        raise RuntimeError("缺少 BNU-ToolBox 主程序目录")
    from app.core.config_store import (
        AccountSelectionStore,
        GlobalConfig,
        PluginConfigStore,
    )

    config = PluginConfigStore(PLUGIN_ID).get()
    account_id = AccountSelectionStore().get(PLUGIN_ID)
    account = GlobalConfig().resolve_account(account_id)
    config.update({
        "username": str(account.get("username") or ""),
        "password": str(account.get("campus_password") or ""),
    })
    return config


def run_autostart() -> int:
    _require_windows_11()
    if PLUGIN_DATA_PATH is None:
        raise RuntimeError("缺少校园网认证插件数据目录")
    data_dir = PLUGIN_DATA_PATH
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bnu-toolbox-campus-network-autostart")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        data_dir / "autostart.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        with _InstanceLock(data_dir / "autostart.lock"):
            config = _load_config()
            if not config.get("autostart"):
                logger.info("autostart disabled; exiting")
                return 0
            from srun_core import connect_with_retries
            result = connect_with_retries(
                config, log=lambda message: logger.info(message))
            logger.info(
                "result: %s", json.dumps(result, ensure_ascii=False))
            return 0
    except Exception as exc:
        logger.exception("campus network autostart failed: %s", exc)
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--home", default="")
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()
    _configure_paths(args.home, args.data_dir)
    try:
        if args.install:
            print(json.dumps(install(), ensure_ascii=False))
        elif args.uninstall:
            print(json.dumps(uninstall(), ensure_ascii=False))
        elif args.status:
            print(json.dumps(status(), ensure_ascii=False))
        elif args.run:
            return run_autostart()
        else:
            parser.error("请指定 --install、--uninstall、--status 或 --run")
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "status": status(),
        }, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

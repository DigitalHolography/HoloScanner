import sys
import os
import re
import tempfile

from importlib import metadata as importlib_metadata
from pathlib import Path

VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"\s*$')
INVALID_PATH_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*]+')

APP_NAME = "HoloScanner"
PACKAGE_NAME = "holo-scanner"
CACHE_FILE_NAME = "holo_scanner_cache.json"
LOG_FILE_NAME = "last_holoscanner_log.txt"

# =======  DATA PATHS =======

def get_app_data_dir() -> Path:
    return _get_app_data_dir()

def get_default_log_path() -> Path:
    return get_app_data_dir() / LOG_FILE_NAME

def get_default_cache_file() -> Path:
    return get_app_data_dir() / CACHE_FILE_NAME

def ensure_app_data_dirs() -> None:
    get_app_data_dir().mkdir(parents=True, exist_ok=True)

# ==============================

# ======= VERSION =======
def app_version() -> str | None:
    env_version = os.getenv("HOLO_SCANNER_VERSION", "").strip()
    if env_version:
        return env_version

    for package_name in (PACKAGE_NAME, APP_NAME):
        try:
            return importlib_metadata.version(package_name)
        except importlib_metadata.PackageNotFoundError:
            pass

    for root in _resource_roots():
        version = _read_version_from_pyproject(root / "pyproject.toml")
        if version:
            return version
        version = _read_version_from_file(root / "version_holoscanner.txt")
        if version:
            return version
    return None
# ==============================

def _get_app_data_dir():
    appdata = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
    base_dir = Path(appdata) if appdata else Path(tempfile.gettempdir())
    return base_dir / APP_NAME / _app_version_subdir_name()

def _app_version_subdir_name():
    safe_version = INVALID_PATH_CHARS_PATTERN.sub("-", app_version() or "").rstrip(" .")
    return safe_version or APP_NAME

def _resource_roots() -> list[Path]:
    roots: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        roots.append(Path(frozen_root))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent)
    roots.append(Path.cwd())
    return roots

def _read_version_from_pyproject(pyproject_path: Path) -> str | None:
    try:
        lines = pyproject_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        match = VERSION_PATTERN.match(line)
        if match:
            return match.group(1)
    return None

def _read_version_from_file(version_path: Path) -> str | None:
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return version or None

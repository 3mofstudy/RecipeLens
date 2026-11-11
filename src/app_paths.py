"""集中管理路徑：原始碼執行時沿用專案資料夾；安裝版區分程式、資源與使用者資料。"""
import os
from pathlib import Path
import sys

FROZEN = getattr(sys, "frozen", False)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def documents_dir():
    """Windows「文件」資料夾，支援 OneDrive 等重新導向的位置。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_PERSONAL = 5，即使用者的「文件」。
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    return Path.home() / "Documents"


def local_app_data():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


# 唯讀資源：assets、picker_page.html、內嵌的 Google 用戶端。
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) if FROZEN else PROJECT_ROOT
# 安裝資料夾：RecipeLens.exe 與 tools/（FFmpeg、yt-dlp、Deno）。
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else PROJECT_ROOT
# 設定與 Google 授權。安裝資料夾可能唯讀，而且升級或解除安裝時不應刪除使用者資料。
DATA_ROOT = local_app_data() / "RecipeLens" if FROZEN else PROJECT_ROOT
# 預設食譜輸出位置，可在進階設定更改。
OUTPUT_ROOT = documents_dir() / "RecipeLens" if FROZEN else PROJECT_ROOT / "output"

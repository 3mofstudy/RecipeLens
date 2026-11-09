"""尋找環境工具，也支援尚未繼承更新 PATH 的 Windows 視窗。"""
import os
from pathlib import Path
import shutil
import sys


def user_path():
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return os.path.expandvars(value)
    except OSError:
        return ""


def find_tool(name):
    project_tools = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin"
    if name in {"ffmpeg", "ffprobe"}:
        executable = project_tools / f"{name}.exe"
        if executable.is_file():
            return str(executable)
    installed = shutil.which(name)
    if installed:
        return installed
    # uv 的直譯器旁邊亦可能有 yt-dlp，而啟動者未把該目錄加到 PATH。
    search_path = os.pathsep.join([str(Path(sys.executable).parent), user_path()])
    installed = shutil.which(name, path=search_path)
    if installed:
        return installed
    local = Path.home() / "AppData" / "Local"
    if name in {"ffmpeg", "ffprobe"}:
        candidates = sorted((local / "RecipeLens" / "ffmpeg").glob(f"*/bin/{name}.exe"))
        if candidates:
            return str(candidates[-1])
    if name == "codex":
        executable = local / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if executable.is_file():
            return str(executable)
    if name == "claude":
        for executable in (Path.home() / ".local" / "bin" / "claude.exe",
                           Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd"):
            if executable.is_file():
                return str(executable)
    return None


REQUIRED_TOOLS = ("yt-dlp", "ffmpeg", "ffprobe")
AI_TOOLS = ("codex", "claude")


def find_tools():
    """AI 工具只需安裝所選的一種，找不到時值為 None。"""
    return {name: find_tool(name) for name in (*REQUIRED_TOOLS, *AI_TOOLS)}

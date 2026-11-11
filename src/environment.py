"""尋找環境工具，也支援尚未繼承更新 PATH 的 Windows 視窗。"""
import os
from pathlib import Path
import shutil
import sys
from .app_paths import APP_ROOT


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
    # 安裝版優先使用安裝資料夾內附的工具，不受使用者 PATH 上的舊版影響。
    if getattr(sys, "frozen", False):
        tools = APP_ROOT / "tools"
        bundled = {
            "yt-dlp": tools / "yt-dlp.exe",
            "ffmpeg": tools / "ffmpeg" / "bin" / "ffmpeg.exe",
            "ffprobe": tools / "ffmpeg" / "bin" / "ffprobe.exe",
            "deno": tools / "deno.exe",
        }.get(name)
        if bundled and bundled.is_file():
            return str(bundled)
    # 專案由 uv 鎖定的下載器優先，避免 PATH 上的舊版遮蔽 .venv。
    if name == "yt-dlp":
        executable = Path(sys.executable).parent / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
        if executable.is_file():
            return str(executable)
    project_tools = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin"
    if name in {"ffmpeg", "ffprobe"}:
        executable = project_tools / f"{name}.exe"
        if executable.is_file():
            return str(executable)
    installed = shutil.which(name)
    if installed and not is_app_alias(name, installed):
        return installed
    # uv 的直譯器旁邊亦可能有 yt-dlp，而啟動者未把該目錄加到 PATH。
    search_path = os.pathsep.join([str(Path(sys.executable).parent), user_path()])
    installed = shutil.which(name, path=search_path)
    if installed and not is_app_alias(name, installed):
        return installed
    local = Path.home() / "AppData" / "Local"
    if name in {"ffmpeg", "ffprobe"}:
        candidates = sorted((local / "RecipeLens" / "ffmpeg").glob(f"*/bin/{name}.exe"))
        if candidates:
            return str(candidates[-1])
    if name == "codex":
        return codex_from_desktop_or_standalone(local)
    if name == "claude":
        return claude_from_desktop_or_standalone()
    return None


def is_app_alias(name, path):
    """Microsoft Store 的 App 執行別名（WindowsApps）：舊版 Claude 桌面版的 claude.exe 會開啟桌面 App 而非 CLI。"""
    return name in {"codex", "claude"} and "windowsapps" in str(path).lower()


def version_key(path):
    """依資料夾名稱的版本號排序，例如 2.1.308；無法解析時排最前。"""
    parts = []
    for piece in path.parent.name.split("."):
        parts.append(int(piece) if piece.isdigit() else -1)
    return parts, path.stat().st_mtime


def claude_from_desktop_or_standalone(home=None):
    """找 Claude Code：獨立安裝的 CLI，或 Claude 桌面版「Code」分頁下載的內附 Claude Code。

    桌面版會把 Claude Code 放在 %APPDATA%\\Claude\\claude-code\\<版本>\\claude.exe；
    Microsoft Store 版的實際位置在 %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude\\claude-code。
    取最高版本。此路徑非官方文件，桌面版改版時可能需要調整。
    """
    home = Path(home) if home else Path.home()
    for executable in (home / ".local" / "bin" / "claude.exe",
                       home / "AppData" / "Roaming" / "npm" / "claude.cmd"):
        if executable.is_file():
            return str(executable)
    roots = [home / "AppData" / "Roaming" / "Claude" / "claude-code"]
    roots += sorted((home / "AppData" / "Local" / "Packages").glob("Claude_*/LocalCache/Roaming/Claude/claude-code"))
    bundled = [path for root in roots for path in root.glob("*/claude.exe") if path.is_file()]
    if bundled:
        return str(max(bundled, key=version_key))
    return None


def codex_from_desktop_or_standalone(local=None):
    """找 Codex：獨立安裝的 CLI，或 ChatGPT 桌面版（原 Codex 桌面版）內附的 CLI。

    桌面版從 Microsoft Store 安裝，內附的 codex.exe 在 WindowsApps 內，外部程式通常無權執行；
    桌面版啟動後會把它複製到 %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<雜湊>\\codex.exe，
    雜湊隨版本變動，因此取最新的一份。此路徑非官方文件，桌面版改版時可能需要調整。
    """
    local = Path(local) if local else Path.home() / "AppData" / "Local"
    override = os.environ.get("CODEX_CLI_PATH", "").strip()
    if override and Path(override).is_file():
        return override
    standalone = local / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    if standalone.is_file():
        return str(standalone)
    relocated = [path for path in (local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe")
                 if not path.parent.name.startswith(".") and path.is_file()]
    if relocated:
        return str(max(relocated, key=lambda path: path.stat().st_mtime))
    plugin_server = Path.home() / ".codex" / "plugins" / ".plugin-appserver" / "codex.exe"
    if plugin_server.is_file():
        return str(plugin_server)
    return None


REQUIRED_TOOLS = ("yt-dlp", "ffmpeg", "ffprobe")
AI_TOOLS = ("codex", "claude")


def find_tools():
    """AI 工具只需安裝所選的一種，找不到時值為 None。"""
    return {name: find_tool(name) for name in (*REQUIRED_TOOLS, *AI_TOOLS)}

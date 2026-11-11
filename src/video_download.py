"""下載器共用的網址驗證與 yt-dlp 呼叫。"""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .media import run
from .environment import find_tool


def js_runtime_options():
    """明確啟用已安裝的 JS runtime，yt-dlp 預設不會啟用 Node。"""
    for name in ("deno", "node"):
        executable = find_tool(name)
        if executable:
            return ["--js-runtimes", f"{name}:{executable}"]
    return []


VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".flv"}


def downloaded_video(work, printed):
    """由 yt-dlp 印出的路徑找回影片。

    輸出資料夾含中文時，舊版或非 UTF-8 主控台可能把路徑印成亂碼；
    檔名固定為 source.<副檔名>，因此只取檔名並在工作資料夾內確認，找不到再掃描。
    """
    work = Path(work)
    candidate = work / Path(printed.strip()).name
    if candidate.is_file():
        return candidate.resolve()
    videos = sorted(path for path in work.glob("source.*")
                    if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES)
    if videos:
        return videos[0].resolve()
    raise ValueError(f"yt-dlp 回報已下載，但在工作資料夾找不到影片檔：{printed.strip()}")


def detect_platform(url):
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("請輸入 HTTPS 影片網址。")
    host = parsed.hostname
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return "YouTube"
    if host in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"}:
        return "Facebook"
    raise ValueError("網址必須來自 YouTube 或 Facebook。")


def download(url, work, tools, subtitles="auto"):
    result = run(
        [tools["yt-dlp"], *js_runtime_options(), "--ignore-config", "--encoding", "utf-8", "--no-playlist", "--no-progress",
         "--no-simulate", "--write-description", "--write-info-json",
         "--ffmpeg-location", str(Path(tools["ffmpeg"]).parent),
         "--no-write-subs", "--no-write-auto-subs",
         "-f", "bv*[height<=720]+ba/b[height<=720]/b", "-o", "source.%(ext)s",
         "--print", "after_move:filepath", "--", url],
        folder=work,
    )
    if not result:
        raise ValueError("未取得影片，請確認公開影片網址。")
    video = downloaded_video(work, result.splitlines()[-1])
    if subtitles in {"original", "auto"}:
        download_captions(url, work, tools)
    return video


def download_captions(url, work, tools):
    """字幕下載失敗不影響已下載的影片，交由轉換流程改用語音轉錄。"""
    metadata_file = work / "source.info.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    tracks = metadata.get("subtitles") or {}
    source = "平台人工字幕"
    if not tracks:
        tracks = metadata.get("automatic_captions") or {}
        source = "平台自動字幕"
    languages = [language for language, formats in tracks.items()
                 if formats and language != "live_chat"]
    if not languages:
        (work / "subtitle-status.txt").write_text("平台沒有可下載的字幕", encoding="utf-8")
        return
    languages.sort(key=lambda language: (
        not language.startswith("zh-Hant"), not language.startswith("zh"),
        not language.endswith("-orig"), not language.startswith("en"), language,
    ))
    language = languages[0]
    # 避免語言代碼中的正規表示式字元改變 yt-dlp 選取範圍。
    try:
        run(
            [tools["yt-dlp"], *js_runtime_options(), "--ignore-config", "--encoding", "utf-8", "--no-playlist", "--skip-download",
             "--write-subs", "--write-auto-subs", "--sub-langs", re.escape(language),
             "--sub-format", "vtt", "-o", "source.%(ext)s", "--", url],
            folder=work,
        )
        (work / "subtitle-status.txt").write_text(f"{source}（{language}）", encoding="utf-8")
    except ValueError as error:
        # 清掉未完成的字幕，避免把半份文字當作完整字幕。
        for subtitle in work.glob("source.*.vtt"):
            subtitle.unlink()
        (work / "subtitle-status.txt").write_text(f"字幕下載失敗：{error}", encoding="utf-8")


def read_metadata(url, work, tools):
    return json.loads(run(
        [tools["yt-dlp"], *js_runtime_options(), "--ignore-config", "--encoding", "utf-8", "--no-playlist", "--skip-download",
         "--dump-single-json", "--", url], folder=work,
    ))

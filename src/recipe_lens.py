"""共用轉換流程與命令列入口。"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from .ai_recipe import AI_PROVIDERS, PROVIDER_TOOLS, cli_logged_in, cli_login, interpret
from .setup_check import missing_tool_message
from .environment import find_tools
from .document_export import export_documents, validate_filename
from .facebook_download import download_facebook
from .media import SPEECH_LANGUAGES, get_transcript, plain_subtitle_text, run, screenshot
from .recipe_export import export_recipe
from .recovery import job_workspace, perform
from .video_download import detect_platform
from .youtube_download import download_youtube, has_complete_recipe, inspect_youtube

from .app_paths import OUTPUT_ROOT

DEFAULT_OUTPUT = OUTPUT_ROOT
PLATFORM_PREFIX = {"Facebook": "Facebook", "YouTube": "Youtuber"}


def recipe_stem(platform, title, channel=None):
    """依「平台-頻道名稱-食譜名稱」命名。"""
    name = re.sub(r"[【\[(（<《].*?[】\])）>》]", "", title or "")
    name = re.sub(r"#\S+", "", name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:40].strip(" .") or "食譜"
    channel = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", channel or "")
    channel = re.sub(r"\s+", " ", channel).strip(" .")[:40].strip(" .") or "未知頻道"
    return validate_filename(f"{PLATFORM_PREFIX[platform]}-{channel}-{name}")


def unique_folder(parent, name):
    target = parent / name
    index = 2
    while target.exists():
        target = parent / f"{name}-{index}"
        index += 1
    return target


def convert_video(url, output=DEFAULT_OUTPUT, *, platform=None, subtitle_mode="auto",
                  keep_subtitles=False, subtitle_file=None, model=None, progress=print,
                  speech_language="其他", file_stem=None, provider="Codex", on_error=None,
                  local_formats=("md", "pdf", "docx")):
    local_formats = tuple(local_formats)
    if any(suffix not in {"md", "pdf", "docx"} for suffix in local_formats):
        raise ValueError("不支援的本機輸出類型。")
    documents = tuple(suffix for suffix in local_formats if suffix != "md")
    if file_stem is not None:
        file_stem = validate_filename(file_stem)
    detected = detect_platform(url)
    if platform and platform != detected:
        raise ValueError("選取的平台與網址不符，請確認後再執行。")
    if subtitle_mode not in {"auto", "embedded", "none", "original"}:
        raise ValueError("不支援的字幕選項。")
    if provider not in AI_PROVIDERS:
        raise ValueError("AI 平台請選擇 Codex 或 Claude。")
    if speech_language not in SPEECH_LANGUAGES:
        raise ValueError("不支援的語音語言。")
    if keep_subtitles and subtitle_mode != "original":
        raise ValueError("只有原始字幕檔模式可附上完整字幕。")
    tools = find_tools()
    missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe") if not tools[name]]
    if missing:
        raise ValueError("找不到工具，請安裝並加入 PATH：" + "、".join(missing))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with job_workspace(output, progress) as folder:
        work = Path(folder)
        metadata = {}
        direct = False
        if detected == "YouTube":
            progress("正在檢查 YouTube 資訊欄…")
            metadata = perform("檢查 YouTube 資訊欄", lambda: inspect_youtube(url, work, tools), on_error)
            direct = has_complete_recipe(metadata.get("description") or "")
        ai_tool = tools.get(PROVIDER_TOOLS[provider])
        if not direct and not ai_tool:
            raise ValueError(missing_tool_message(provider))
        if not direct and cli_logged_in(provider, ai_tool) is False:
            account = "Pro／Max 月租帳號" if provider == "Claude" else "ChatGPT 帳號"
            progress(f"{provider} 尚未登入，已開啟瀏覽器，請用{account}登入…")
            perform("AI 登入", lambda: cli_login(provider, ai_tool), on_error)
        progress("正在下載影片…")
        downloader = download_youtube if detected == "YouTube" else download_facebook
        download_mode = "none" if subtitle_file and subtitle_mode == "original" else subtitle_mode
        video = perform("下載影片", lambda: downloader(url, work, tools, download_mode), on_error)
        # 兩個平台下載時都會保存 metadata；沿用資料，避免額外網路請求。
        metadata_file = work / "source.info.json"
        if metadata_file.is_file():
            try:
                downloaded = json.loads(metadata_file.read_text(encoding="utf-8"))
                if isinstance(downloaded, dict):
                    metadata = {**metadata, **downloaded}
            except (ValueError, OSError):
                pass
        duration = float(perform("讀取影片長度", lambda: run(
            [tools["ffprobe"], "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)], folder=work,
        ), on_error))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("無法確認影片長度。")
        original = ""
        subtitle_source = "本機語音轉錄"
        if subtitle_mode == "original":
            if subtitle_file:
                original = Path(subtitle_file).read_text(encoding="utf-8-sig")
                subtitle_source = "本機原始字幕檔"
            else:
                subtitles = sorted(work.glob("source.*.vtt"))
                subtitles.sort(key=lambda p: ("zh-Hant" not in p.name, "zh" not in p.name, p.name))
                if subtitles:
                    original = subtitles[0].read_text(encoding="utf-8-sig")
                    status_file = work / "subtitle-status.txt"
                    subtitle_source = (status_file.read_text(encoding="utf-8")
                                       if status_file.is_file() else "平台字幕")
                else:
                    progress("無法取得平台字幕，改用本機語音轉錄…")
            if not original.strip() and (not direct or keep_subtitles):
                original = perform("字幕／語音辨識", lambda: get_transcript(
                    work, video, tools["ffmpeg"], tools["ffprobe"], speech_language=speech_language), on_error)
        destination = output / f"recipe-{uuid4().hex[:12]}"
        if direct:
            progress("資訊欄包含食材與做法，直接保留原文…")
            result = perform("資訊欄與參考畫面匯出", lambda: export_description(
                metadata, url, duration, tools["ffmpeg"], video, work, destination), on_error)
            title = metadata.get("title")
        else:
            progress("正在讀取字幕或辨識語音…")
            transcript = (original if subtitle_mode == "original" else
                          perform("字幕／語音辨識", lambda: get_transcript(
                              work, video, tools["ffmpeg"], tools["ffprobe"],
                              speech_language=speech_language), on_error))
            progress(f"正在由 {provider} 判讀食譜與影片畫面…")
            recipe = perform("AI 判讀", lambda: interpret(work, ai_tool, tools["ffmpeg"], video,
                               duration, transcript, model, subtitle_mode == "embedded",
                               provider=provider), on_error)
            result = perform("食譜與截圖匯出", lambda: export_recipe(
                recipe, url, duration, tools["ffmpeg"], video, work, destination), on_error)
            title = recipe.get("title")
        if keep_subtitles:
            with result.open("a", encoding="utf-8") as stream:
                stream.write(f"\n\n## 完整字幕文字\n\n文字來源：{subtitle_source}\n\n")
                text = plain_subtitle_text(original) or "影片沒有可辨識的字幕或語音。"
                # 純文字，不含時間標記；行尾兩個空白讓每句字幕各自換行。
                escaped = (re.sub(r"^(\d+)([.)])", r"\1\\\2", re.sub(r"^([#>*+\-=|`~])", r"\\\1", line))
                           for line in text.splitlines())
                stream.write("  \n".join(escaped) + "\n")
        channel = metadata.get("channel") or metadata.get("uploader") or metadata.get("creator")
        file_stem = file_stem or recipe_stem(detected, title, channel)
        if result.stem != file_stem:
            result = result.rename(result.with_name(f"{file_stem}.md"))
        # 資料夾與檔案同名，方便在輸出位置辨識。
        folder_target = unique_folder(output, file_stem)
        result = result.parent.rename(folder_target) / result.name
        if documents:
            progress("正在儲存選取的本機文件…")
            try:
                perform("PDF／DOCX 轉檔", lambda: export_documents(
                    result, documents, output_dir=result.parent), on_error)
            except Exception as error:
                detail = str(error).strip() or type(error).__name__
                raise RuntimeError(f"Markdown 與圖片已保留於 {result.parent}，但所選文件轉檔未完成：{detail}") from error
        return result


def export_description(metadata, url, duration, ffmpeg, video, work, destination):
    staged = work / "recipe"
    images = staged / "images"
    images.mkdir(parents=True, exist_ok=True)
    lines = [f"# {metadata.get('title') or '影片食譜'}", "", f"來源影片：<{url}>",
             "", "## 發布者資訊欄原文", "", metadata["description"],
             "", "## 影片參考畫面", "",
             "以下為均勻取樣畫面，供對照影片，尚未與料理步驟逐一配對。", ""]
    for index in range(6):
        seconds = duration * (index + 0.5) / 6
        filename = f"reference-{index + 1:02d}.jpg"
        screenshot(ffmpeg, video, seconds, images / filename, work)
        lines.extend([f"![影片 {seconds:.1f} 秒](images/{filename})", ""])
    (staged / "食譜.md").write_text("\n".join(lines), encoding="utf-8")
    staged.rename(destination)
    return destination / "食譜.md"


def save_result(source, target):
    """複製圖片並原子替換 Markdown，避免損壞既有檔案。"""
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    asset_name = f"recipe_images_{uuid4().hex[:8]}"
    assets = target.parent / asset_name
    temporary = None
    try:
        shutil.copytree(source.parent / "images", assets)
        text = source.read_text(encoding="utf-8").replace("](images/", f"]({asset_name}/")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(target)
    except Exception:
        if temporary:
            temporary.unlink(missing_ok=True)
        if assets.is_dir():
            shutil.rmtree(assets)
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description="公開料理影片轉繁體中文食譜。")
    parser.add_argument("url")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider", choices=list(AI_PROVIDERS), default="Codex",
                        help="判讀食譜的 AI 平台")
    parser.add_argument("--model")
    parser.add_argument("--name", help="本機 MD、PDF、DOCX 共用檔名，不含副檔名；省略時命名為「平台-頻道名稱-食譜名稱」")
    parser.add_argument("--subtitle-mode", choices=["auto", "embedded", "none", "original"], default="auto")
    parser.add_argument("--keep-subtitles", action="store_true")
    parser.add_argument("--subtitle-file", type=Path)
    parser.add_argument("--speech-language", choices=SPEECH_LANGUAGES, default="其他")
    args = parser.parse_args()
    try:
        result = convert_video(args.url, args.output, model=args.model,
                               subtitle_mode=args.subtitle_mode, keep_subtitles=args.keep_subtitles,
                               subtitle_file=args.subtitle_file, speech_language=args.speech_language,
                               file_stem=args.name, provider=args.provider)
        print(f"已匯出：{result}")
    except Exception as error:
        parser.exit(1, f"處理失敗：{error}\n")


if __name__ == "__main__":
    main()

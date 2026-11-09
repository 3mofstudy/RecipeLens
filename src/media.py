"""影音處理共用函數。"""
import html
import re
import subprocess
from pathlib import Path

SPEECH_LANGUAGES = ("國語", "粵語", "閩南語", "其他")
# Windows 上執行外部工具時不跳出黑色命令視窗
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def speech_settings(language):
    if language not in SPEECH_LANGUAGES:
        raise ValueError("語音語言請選擇國語、粵語、閩南語或其他。")
    if language == "粵語":
        return "large-v3-turbo", "yue", "以下是粵語料理教學，請以繁體中文記錄食材與做法。"
    if language == "閩南語":
        # Whisper 沒有閩南語語言代碼，只能以中文解碼及語境提示輔助。
        return "large-v3-turbo", "zh", "以下是臺灣閩南語（台語）料理教學，請以繁體中文記錄食材與做法。"
    if language == "國語":
        return "small", "zh", "以下是國語料理教學，請以繁體中文記錄食材與做法。"
    return "small", None, None

def run(command, *, folder, prompt=None, timeout=900, env=None):
    result = subprocess.run(
        command, cwd=folder, input=prompt, capture_output=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env,
        creationflags=NO_WINDOW,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        if Path(command[0]).stem == "codex":
            errors = [line for line in detail.splitlines() if line.startswith("ERROR:")]
            if errors:
                detail = errors[-1]
        raise ValueError(f"{Path(command[0]).stem} 執行失敗：\n{detail[-3000:]}")
    return result.stdout.strip()


_TIMING = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}\s*-->")
_SECONDS = re.compile(r"^\[\d+(?:\.\d+)?\s*秒\]\s*")


def plain_subtitle_text(raw):
    """移除 VTT／SRT 標頭、序號、時間軸、格式標籤與語音轉錄的秒數標記，只保留字幕文字。

    YouTube 自動字幕會滾動重複上一行，相同文字在近幾行內出現時只保留一次。
    """
    lines, skip_block = [], False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            skip_block = False
            continue
        if skip_block or line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if line.isdigit() or _TIMING.search(line):
            continue
        line = _SECONDS.sub("", line)
        line = html.unescape(re.sub(r"<[^>]*>", "", line)).replace("\u200b", "").strip()
        if line and line not in lines[-3:]:
            lines.append(line)
    return "\n".join(lines)


def get_transcript(work, video, ffmpeg, ffprobe, speech_language="其他"):
    model_name, language_code, prompt = speech_settings(speech_language)
    subtitles = sorted(work.glob("source.*.vtt"))
    if subtitles:
        # Keep the cue times so Codex can associate speech with video frames.
        return subtitles[0].read_text(encoding="utf-8-sig")

    audio_stream = run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video)],
        folder=work,
    )
    if not audio_stream:
        return ""

    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise ValueError("此影片沒有可用字幕。請安裝 faster-whisper 後重試。") from error

    print(f"正在辨識語音（{speech_language}，首次使用會下載 {model_name} 模型）…", flush=True)
    audio = work / "audio.wav"
    run(
        [ffmpeg, "-v", "error", "-i", str(video), "-vn", "-ac", "1",
         "-ar", "16000", str(audio)],
        folder=work,
    )
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(audio), vad_filter=True, language=language_code, initial_prompt=prompt,
    )
    return "\n".join(f"[{part.start:.2f} 秒] {part.text.strip()}" for part in segments)


def screenshot(ffmpeg, video, seconds, target, work):
    run(
        [ffmpeg, "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(video),
         "-map", "0:v:0", "-frames:v", "1", "-vf",
         "scale=960:960:force_original_aspect_ratio=decrease",
         "-q:v", "3", "-update", "1", str(target)],
        folder=work,
    )
    if not target.is_file():
        raise ValueError(f"無法擷取第 {seconds:.2f} 秒的畫面。")



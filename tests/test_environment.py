"""離線測試環境與主要流程，從專案根目錄執行 python -m unittest tests.test_environment。"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import environment, recipe_lens
from src.video_download import detect_platform
from src.youtube_download import has_complete_recipe
from src.media import get_transcript, speech_settings
from src.video_download import js_runtime_options


class EnvironmentTests(unittest.TestCase):
    def test_project_downloader_wins_over_global_path(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "yt-dlp.exe"
            executable.touch()
            with patch.object(environment.sys, "executable", str(Path(folder) / "python.exe")), \
                    patch.object(environment.shutil, "which", return_value="old-global-yt-dlp"):
                self.assertEqual(environment.find_tool("yt-dlp"), str(executable))

    def test_node_is_explicitly_enabled_when_deno_missing(self):
        with patch("src.video_download.find_tool", side_effect=lambda name: "C:/node.exe" if name == "node" else None):
            self.assertEqual(js_runtime_options(), ["--js-runtimes", "node:C:/node.exe"])

    def test_speech_language_reaches_recognizer(self):
        expected = {
            "國語": ("small", "zh"),
            "粵語": ("large-v3-turbo", "yue"),
            "閩南語": ("large-v3-turbo", "zh"),
            "其他": ("small", None),
        }
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            for label, (model_name, code) in expected.items():
                with (
                    self.subTest(language=label),
                    patch("src.media.run", return_value="0"),
                    patch("faster_whisper.WhisperModel") as model,
                ):
                    model.return_value.transcribe.return_value = (
                        [SimpleNamespace(start=1.0, text="雞蛋兩顆")], None,
                    )
                    text = get_transcript(work, work / "video.mp4", "ffmpeg", "ffprobe",
                                          speech_language=label)
                    model.assert_called_once_with(model_name, device="cpu", compute_type="int8")
                    self.assertEqual(model.return_value.transcribe.call_args.kwargs["language"], code)
                    self.assertIn("雞蛋兩顆", text)
            with self.assertRaises(ValueError):
                speech_settings("未知選項")

    def test_installed_tools(self):
        tools = environment.find_tools()
        self.assertFalse([name for name in environment.REQUIRED_TOOLS if not tools[name]],
                         "缺少工具，請依 readme.md 安裝。")
        # GitHub Actions 打包環境不安裝也不登入 AI CLI。
        if not os.environ.get("CI"):
            self.assertTrue(any(tools[name] for name in environment.AI_TOOLS),
                            "請安裝 Codex CLI 或 Claude Code CLI 其中一種。")
        for name in ("ffmpeg", "ffprobe"):
            result = subprocess.run([tools[name], "-version"], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0)

    def test_ffmpeg_without_inherited_path(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test")
            with (
                patch.object(environment, "__file__", str(Path(folder) / "src" / "environment.py")),
                patch.object(environment.shutil, "which", return_value=None),
                patch.object(environment, "user_path", return_value=""),
            ):
                self.assertEqual(environment.find_tool("ffmpeg"), str(executable))

    def test_platform(self):
        self.assertEqual(detect_platform("https://youtu.be/example"), "YouTube")
        self.assertEqual(detect_platform("https://fb.watch/example"), "Facebook")
        with self.assertRaises(ValueError):
            detect_platform("https://youtube.com.example.org/video")

    def test_missing_subtitles_falls_back_to_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def export(recipe, url, duration, ffmpeg, video, work, destination):
                destination.mkdir()
                result = destination / "食譜.md"
                result.write_text("# 食譜", encoding="utf-8")
                return result

            with (
                patch.object(recipe_lens, "find_tools", return_value=dict.fromkeys(
                    ("yt-dlp", "ffmpeg", "ffprobe", "codex"), "tool")),
                patch.object(recipe_lens, "download_facebook", return_value=root / "video.mp4"),
                patch.object(recipe_lens, "run", return_value="10"),
                patch.object(recipe_lens, "get_transcript", return_value="雞蛋兩顆") as speech,
                patch.object(recipe_lens, "interpret", return_value={}) as ai,
                patch.object(recipe_lens, "export_recipe", side_effect=export),
            ):
                result = recipe_lens.convert_video(
                    "https://fb.watch/test", root / "out", subtitle_mode="original",
                    keep_subtitles=True, progress=lambda text: None,
                )
                speech.assert_called_once()
                self.assertEqual(ai.call_args.args[5], "雞蛋兩顆")
                text = result.read_text(encoding="utf-8")
                self.assertIn("本機語音轉錄", text)
                self.assertIn("雞蛋兩顆", text)

    def test_description_and_export_without_ai(self):
        description = "材料\n雞蛋 2 顆\n牛奶 100 ml\n做法\n1. 加入牛奶\n2. 拌勻煎熟"
        self.assertTrue(has_complete_recipe(description))
        self.assertFalse(has_complete_recipe("材料 雞蛋，歡迎訂閱"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subtitle = root / "字幕.srt"
            subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\n雞蛋兩顆", encoding="utf-8")

            def download(url, work, tools, mode):
                video = work / "source.mp4"
                video.write_bytes(b"video")
                return video

            def screenshot(ffmpeg, video, seconds, target, work):
                from PIL import Image
                Image.new("RGB", (120, 90), "white").save(target, format="JPEG")

            with (
                patch.object(recipe_lens, "find_tools", return_value=dict.fromkeys(
                    ("yt-dlp", "ffmpeg", "ffprobe", "codex"), "tool")),
                patch.object(recipe_lens, "inspect_youtube", return_value={
                    "title": "牛奶蛋", "description": description}),
                patch.object(recipe_lens, "download_youtube", side_effect=download),
                patch.object(recipe_lens, "run", return_value="10"),
                patch.object(recipe_lens, "screenshot", side_effect=screenshot),
                patch.object(recipe_lens, "interpret") as ai,
                patch.object(recipe_lens, "get_transcript") as speech,
            ):
                result = recipe_lens.convert_video(
                    "https://youtu.be/test", root / "out", subtitle_mode="original",
                    subtitle_file=subtitle, keep_subtitles=True, progress=lambda text: None,
                    file_stem="牛奶蛋",
                )
                ai.assert_not_called()
                speech.assert_not_called()
                self.assertEqual(result.name, "牛奶蛋.md")
                self.assertTrue(result.with_suffix(".pdf").is_file())
                self.assertTrue(result.with_suffix(".docx").is_file())
                saved = recipe_lens.save_result(result, root / "另存位置" / "食譜.md")
                text = saved.read_text(encoding="utf-8")
                self.assertIn(description, text)
                self.assertIn("雞蛋兩顆", text)
                references = re.findall(r"\]\((recipe_images_[^)]+)\)", text)
                self.assertEqual(len(references), 6)
                self.assertTrue(all((saved.parent / path).is_file() for path in references))


if __name__ == "__main__":
    unittest.main(verbosity=2)

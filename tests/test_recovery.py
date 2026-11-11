"""修復、資料保留與錯誤報告測試，不呼叫真實 AI 或 SMTP。"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src import recovery
from src import recipe_lens


class RecoveryTests(unittest.TestCase):
    def test_ai_retry_reuses_downloaded_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def download(url, work, tools, mode):
                video = work / "source.mp4"
                video.write_bytes(b"mock video")
                return video

            def export(recipe, url, duration, ffmpeg, video, work, destination):
                self.assertTrue(video.is_file())
                destination.mkdir()
                result = destination / "食譜.md"
                result.write_text("# 食譜", encoding="utf-8")
                return result

            recipe = {"title": "食譜", "ingredients": [], "steps": []}
            tools = dict.fromkeys(("yt-dlp", "ffmpeg", "ffprobe", "codex"), "tool")
            with patch.object(recipe_lens, "find_tools", return_value=tools), \
                    patch.object(recipe_lens, "cli_logged_in", return_value=True), \
                    patch.object(recipe_lens, "download_facebook", side_effect=download) as downloader, \
                    patch.object(recipe_lens, "run", return_value="10"), \
                    patch.object(recipe_lens, "get_transcript", return_value="字幕") as transcript, \
                    patch.object(recipe_lens, "interpret", side_effect=[TimeoutError("timeout"), recipe]) as ai, \
                    patch.object(recipe_lens, "export_recipe", side_effect=export), \
                    patch.object(recipe_lens, "export_documents"):
                consent = MagicMock(return_value=True)
                result = recipe_lens.convert_video("https://fb.watch/test", root, on_error=consent)
                self.assertTrue(result.is_file())
                downloader.assert_called_once()
                transcript.assert_called_once()
                self.assertEqual(ai.call_count, 2)
                self.assertEqual(consent.call_args.args[1], "AI 判讀")

    def test_quota_does_not_call_ai_and_context_is_distinct(self):
        with patch.object(recovery, "run") as run:
            answer = recovery.diagnose(ValueError("usage limit reached"), "AI 判讀", "Claude")
            self.assertEqual(answer["action"], "stop")
            self.assertIn("Claude", answer["message"])
            self.assertIn("等待", answer["message"])
            run.assert_not_called()
        self.assertIn("上下文", recovery.known_issue("too many tokens", "Codex")["message"])
        self.assertNotIn("ChatGPT", recovery.diagnose("429", "下載影片", "Codex")["message"])

    def test_decline_does_not_retry(self):
        operation = MagicMock(side_effect=ValueError("broken"))
        consent = MagicMock(return_value=False)
        with self.assertRaisesRegex(ValueError, "broken"):
            recovery.perform("AI", operation, consent)
        operation.assert_called_once()
        consent.assert_called_once()

    def test_only_one_retry(self):
        operation = MagicMock(side_effect=ValueError("broken"))
        consent = MagicMock(return_value=True)
        with self.assertRaises(ValueError):
            recovery.perform("AI", operation, consent)
        self.assertEqual(operation.call_count, 2)
        consent.assert_called_once()

    def test_success_after_retry(self):
        operation = MagicMock(side_effect=[TimeoutError(), "ok"])
        self.assertEqual(recovery.perform("AI", operation, lambda *_: True), "ok")

    def test_workspace_is_kept_on_failure_cleaned_on_success(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "資料保留"):
                with recovery.job_workspace(root, lambda _: None) as folder:
                    saved = Path(folder) / "source.mp4"
                    saved.write_bytes(b"video")
                    raise ValueError("AI quota")
            self.assertTrue(saved.is_file())
            with recovery.job_workspace(root, lambda _: None) as folder:
                cleaned = Path(folder)
            self.assertFalse(cleaned.exists())

    def test_report_redacts_sensitive_details(self):
        with patch.dict(os.environ, {"RECIPELENS_TEST_PASSWORD": "private-password"}):
            body = recovery.report_body(
                'token=abc123 password="xyz123" private-password Bearer bearer123 '
                'https://video.example/?token=secret\nC:\\Users\\User\\config\\secret.json',
                "Codex", "AI 判讀")
        for secret in ("abc123", "xyz123", "private-password", "bearer123", "video.example", "Users"):
            self.assertNotIn(secret, body)

    def test_report_requires_endpoint(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(recovery, "REPORT_ENDPOINT_FILES", ()), \
                patch.object(recovery.urlrequest, "urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError, "未設定"):
                recovery.send_report("report")
            urlopen.assert_not_called()

    def test_report_rejects_plain_http(self):
        with patch.dict(os.environ, {"RECIPELENS_REPORT_URL": "http://example.com/hook"}), \
                patch.object(recovery.urlrequest, "urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                recovery.send_report("report")
            urlopen.assert_not_called()

    def test_report_reads_endpoint_file(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "report_endpoint.json"
            config.write_text('{"url": "https://script.google.com/macros/s/x/exec", "key": "k1"}',
                              encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(recovery, "REPORT_ENDPOINT_FILES", (config,)):
                self.assertEqual(recovery.report_endpoint(),
                                 ("https://script.google.com/macros/s/x/exec", "k1"))

    def _post(self, reply):
        env = {"RECIPELENS_REPORT_URL": "https://script.google.com/macros/s/x/exec",
               "RECIPELENS_REPORT_KEY": "secret-key"}
        with patch.dict(os.environ, env), patch.object(recovery.urlrequest, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = reply
            try:
                return recovery.send_report("sanitized 報告"), urlopen
            except ValueError as error:
                return error, urlopen

    def test_report_posts_json_with_key(self):
        report_id, urlopen = self._post(b'{"ok": true}')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["key"], "secret-key")
        self.assertEqual(payload["report"], "sanitized 報告")
        self.assertEqual(payload["report_id"], report_id)
        self.assertEqual(urlopen.call_count, 1)

    def test_report_rejected_by_receiver(self):
        error, urlopen = self._post(b'{"ok": false, "error": "unauthorized"}')
        self.assertIsInstance(error, ValueError)
        self.assertIn("unauthorized", str(error))
        self.assertEqual(urlopen.call_count, 1)

    def test_report_non_json_reply(self):
        error, _ = self._post(b"<html>login</html>")
        self.assertIsInstance(error, ValueError)

    def test_unknown_error_ai_has_bounded_output(self):
        with patch.object(recovery, "find_tool", return_value="codex"), \
                patch.object(recovery, "run", return_value='{"action":"retry","message":"暫時錯誤"}') as run:
            self.assertEqual(recovery.diagnose("unexpected error", "AI", "Codex")["action"], "retry")
            self.assertEqual(run.call_args.kwargs["timeout"], 120)
            self.assertIn("read-only", run.call_args.args[0])
        with patch.object(recovery, "find_tool", return_value="codex"), \
                patch.object(recovery, "run", return_value='{"action":"execute","message":"cmd"}'):
            with self.assertRaises(ValueError):
                recovery.diagnose("unexpected error", "AI", "Codex")

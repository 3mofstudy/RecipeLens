"""驗證「平台-頻道名稱-食譜名稱」命名、Claude 回應解析與 .md 連同圖片上傳，不呼叫真的 AI 或 Google。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from httplib2 import Response
from googleapiclient.errors import HttpError

from src import ai_recipe, cloud_upload, recipe_lens
from src.recipe_lens import recipe_stem
from src.settings import load_settings, save_settings

RECIPE = {"title": "蔥爆豬肉", "ingredients": [{"name": "豬肉", "amount": "300 克"}],
          "steps": [{"instruction": "爆香蔥段", "seconds": 1.5}]}


class NamingTests(unittest.TestCase):
    def test_channel_name_and_fallback(self):
        self.assertEqual(recipe_stem("YouTube", "高麗菜水煎包", "豫魯小學堂"),
                         "Youtuber-豫魯小學堂-高麗菜水煎包")
        self.assertEqual(recipe_stem("Facebook", "蔥爆豬肉", '頻/道:*'),
                         "Facebook-頻道-蔥爆豬肉")
        self.assertEqual(recipe_stem("YouTube", "食譜", " /:* "),
                         "Youtuber-未知頻道-食譜")

    def test_platform_prefix(self):
        self.assertEqual(recipe_stem("Facebook", "蔥爆豬肉"), "Facebook-未知頻道-蔥爆豬肉")
        self.assertEqual(recipe_stem("YouTube", "蔥爆豬肉"), "Youtuber-未知頻道-蔥爆豬肉")

    def test_title_is_cleaned_for_windows(self):
        self.assertEqual(recipe_stem("YouTube", "【阿基師】蔥爆豬肉 #shorts"), "Youtuber-未知頻道-蔥爆豬肉")
        self.assertEqual(recipe_stem("Facebook", 'a/b:c?"'), "Facebook-未知頻道-abc")
        self.assertEqual(recipe_stem("Facebook", ""), "Facebook-未知頻道-食譜")

    def test_convert_names_file_and_folder_from_ai_title(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def download(url, work, tools, mode):
                (work / "source.info.json").write_text(
                    json.dumps({"uploader": "料理頻道"}), encoding="utf-8")
                return root / "video.mp4"

            def export(recipe, url, duration, ffmpeg, video, work, destination):
                destination.mkdir()
                result = destination / "食譜.md"
                result.write_text("# 食譜", encoding="utf-8")
                return result

            with (
                patch.object(recipe_lens, "find_tools", return_value={
                    "yt-dlp": "t", "ffmpeg": "t", "ffprobe": "t", "codex": None, "claude": "claude"}),
                patch.object(recipe_lens, "download_facebook", side_effect=download),
                patch.object(recipe_lens, "run", return_value="10"),
                patch.object(recipe_lens, "get_transcript", return_value=""),
                patch.object(recipe_lens, "interpret", return_value=RECIPE) as ai,
                patch.object(recipe_lens, "export_recipe", side_effect=export),
                patch.object(recipe_lens, "export_documents"),
                patch.object(recipe_lens, "cli_logged_in", return_value=False),
                patch.object(recipe_lens, "cli_login") as login,
            ):
                for expected in ("Facebook-料理頻道-蔥爆豬肉", "Facebook-料理頻道-蔥爆豬肉-2"):
                    result = recipe_lens.convert_video(
                        "https://fb.watch/test", root / "out", subtitle_mode="embedded",
                        provider="Claude", progress=lambda text: None)
                    self.assertEqual(result.name, "Facebook-料理頻道-蔥爆豬肉.md")
                    self.assertEqual(result.parent.name, expected)
                self.assertEqual(ai.call_args.kwargs["provider"], "Claude")
                self.assertEqual(ai.call_args.args[1], "claude")
                login.assert_called_with("Claude", "claude")

    def test_missing_selected_ai_cli_is_reported(self):
        with (
            patch.object(recipe_lens, "find_tools", return_value={
                "yt-dlp": "t", "ffmpeg": "t", "ffprobe": "t", "codex": "codex", "claude": None}),
            tempfile.TemporaryDirectory() as folder,
        ):
            with self.assertRaisesRegex(RuntimeError, "Claude"):
                recipe_lens.convert_video("https://fb.watch/test", folder, provider="Claude",
                                          progress=lambda text: None)


class ClaudeTests(unittest.TestCase):
    def test_claude_command_and_json_parsing(self):
        envelope = {"type": "result", "is_error": False,
                    "result": "以下是結果：\n```json\n" + json.dumps(RECIPE, ensure_ascii=False) + "\n```"}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "claude_logged_in", return_value=True), \
                patch.object(ai_recipe, "run", return_value=json.dumps(envelope)) as run:
            recipe = ai_recipe.interpret_claude(Path(folder), "claude", "claude-sonnet-5-5",
                                                "提示", ["frame-00.jpg"])
        self.assertEqual(recipe["title"], "蔥爆豬肉")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["claude", "-p"])
        self.assertIn("claude-sonnet-5-5", command)
        self.assertNotIn("ANTHROPIC_API_KEY", run.call_args.kwargs["env"])
        self.assertIn("Read", run.call_args.kwargs["prompt"])

    def test_claude_error_is_raised(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "claude_logged_in", return_value=True), patch.object(
                ai_recipe, "run", return_value=json.dumps({"is_error": True, "result": "模型不存在"})):
            with self.assertRaisesRegex(ValueError, "模型不存在"):
                ai_recipe.interpret_claude(Path(folder), "claude", None, "提示", [])

    def test_subscription_env_drops_api_key(self):
        with patch.dict(ai_recipe.os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            self.assertNotIn("ANTHROPIC_API_KEY", ai_recipe.subscription_env())

    def test_expired_login_relogs_in_background_and_retries(self):
        expired = ValueError('claude 執行失敗：{"is_error":true,"result":"Failed to authenticate: '
                             'OAuth session expired and could not be refreshed"}')
        ok = json.dumps({"is_error": False, "result": json.dumps(RECIPE, ensure_ascii=False)})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "claude_logged_in", return_value=True), \
                patch.object(ai_recipe, "claude_login") as login, \
                patch.object(ai_recipe, "run", side_effect=[expired, ok]):
            recipe = ai_recipe.interpret_claude(Path(folder), "claude", None, "提示", [])
        login.assert_called_once_with("claude")
        self.assertEqual(recipe["title"], "蔥爆豬肉")

    def test_login_before_first_use(self):
        ok = json.dumps({"is_error": False, "result": json.dumps(RECIPE, ensure_ascii=False)})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "claude_logged_in", return_value=False), \
                patch.object(ai_recipe, "claude_login") as login, patch.object(ai_recipe, "run", return_value=ok):
            ai_recipe.interpret_claude(Path(folder), "claude", None, "提示", [])
        login.assert_called_once()

    def test_still_failing_after_relogin(self):
        expired = ValueError("claude 執行失敗：Failed to authenticate")
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "claude_logged_in", return_value=True), \
                patch.object(ai_recipe, "claude_login"), patch.object(ai_recipe, "run", side_effect=[expired, expired]):
            with self.assertRaisesRegex(ValueError, "登入 Claude 帳號"):
                ai_recipe.interpret_claude(Path(folder), "claude", None, "提示", [])

    def test_auth_commands_run_hidden_without_api_key(self):
        done = MagicMock(returncode=0, stdout='{"authMethod": "claude.ai"}', stderr="")
        with patch.dict(ai_recipe.os.environ, {"ANTHROPIC_API_KEY": "sk"}), \
                patch.object(ai_recipe.subprocess, "run", return_value=done) as run:
            self.assertTrue(ai_recipe.claude_logged_in("claude"))
            ai_recipe.claude_login("claude")
        self.assertEqual(run.call_args_list[0].args[0], ["claude", "auth", "status"])
        self.assertEqual(run.call_args_list[1].args[0], ["claude", "auth", "login"])
        for call in run.call_args_list:
            self.assertNotIn("ANTHROPIC_API_KEY", call.kwargs["env"])
            self.assertIn("creationflags", call.kwargs)
        done.stdout = '{"authMethod": "none"}'
        with patch.object(ai_recipe.subprocess, "run", return_value=done):
            self.assertFalse(ai_recipe.claude_logged_in("claude"))

    def test_invalid_recipe_rejected(self):
        with self.assertRaises(ValueError):
            ai_recipe.validate_recipe({"title": "x", "ingredients": [], "steps": [{"seconds": 1}]})

    def test_prompt_asks_for_short_recipe_name(self):
        self.assertIn("蔥爆豬肉", ai_recipe.build_prompt(10, [], "", ""))


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_bad_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertEqual(load_settings(path)["formats"], ["md", "pdf", "docx"])
            settings = load_settings(path)
            settings.update(provider="Claude", upload_after=True, formats=["pdf"])
            save_settings(settings, path)
            self.assertEqual(load_settings(path)["provider"], "Claude")
            self.assertEqual(load_settings(path)["formats"], ["pdf"])
            path.write_text('{"provider": "Other", "formats": "x"}', encoding="utf-8")
            self.assertEqual(load_settings(path)["provider"], "Codex")
            path.write_text("壞掉", encoding="utf-8")
            self.assertEqual(load_settings(path)["provider"], "Codex")


class MarkdownImageUploadTests(unittest.TestCase):
    def test_md_upload_includes_images_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "images").mkdir()
            for name in ("step-01.jpg", "step-02.jpg"):
                (root / "images" / name).write_bytes(name.encode())
            source = root / "FB-蔥爆豬肉.md"
            original = "# 蔥爆豬肉\n\n![步驟 1](images/step-01.jpg)\n\n![步驟 2](images/step-02.jpg)\n"
            source.write_text(original, encoding="utf-8")
            service = MagicMock()
            api = service.files.return_value
            ids = iter(["folder-id", "img-1", "img-2", "md-id"])
            api.generateIds.return_value.execute.side_effect = lambda: {"ids": [next(ids)]}
            api.get.return_value.execute.side_effect = HttpError(
                Response({"status": "404"}), b'{"error":"not found"}')
            api.create.return_value.next_chunk.return_value = (None, {"id": "x"})
            result = cloud_upload.upload_recipe(source, ("md",), service=service, parent_id="parent",
                                                progress=lambda text: None)
            bodies = [call.kwargs["body"] for call in api.create.call_args_list]
            self.assertEqual(bodies[0]["name"], "FB-蔥爆豬肉_images")
            self.assertEqual(bodies[0]["parents"], ["parent"])
            self.assertEqual([b["name"] for b in bodies[1:3]], ["step-01.jpg", "step-02.jpg"])
            self.assertEqual({tuple(b["parents"]) for b in bodies[1:3]}, {("folder-id",)})
            self.assertEqual(bodies[3]["name"], "FB-蔥爆豬肉.md")
            self.assertEqual(bodies[3]["parents"], ["parent"])
            uploaded = (root / ".drive" / "FB-蔥爆豬肉.md").read_text(encoding="utf-8")
            self.assertIn("](FB-蔥爆豬肉_images/step-01.jpg)", uploaded)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertIn("2 張圖片", result[-1]["name"])

    def test_recipe_gets_own_folder_with_images_inside(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "images").mkdir()
            (root / "images" / "step-01.jpg").write_bytes(b"1")
            source = root / "YT-蔥爆豬肉.md"
            source.write_text("# 蔥爆豬肉\n\n![步驟 1](images/step-01.jpg)\n", encoding="utf-8")
            service = MagicMock()
            api = service.files.return_value
            ids = iter(["recipe-folder", "images-folder", "img-1", "md-id"])
            api.generateIds.return_value.execute.side_effect = lambda: {"ids": [next(ids)]}
            api.get.return_value.execute.side_effect = HttpError(
                Response({"status": "404"}), b'{"error":"not found"}')
            api.create.return_value.next_chunk.return_value = (None, {"id": "x"})
            result = cloud_upload.upload_recipe(source, ("md",), service=service, parent_id="root09",
                                                new_folder="YT-蔥爆豬肉", progress=lambda text: None)
            bodies = [call.kwargs["body"] for call in api.create.call_args_list]
            self.assertEqual((bodies[0]["name"], bodies[0]["parents"]), ("YT-蔥爆豬肉", ["root09"]))
            self.assertEqual((bodies[1]["name"], bodies[1]["parents"]), ("images", ["recipe-folder"]))
            self.assertEqual(bodies[2]["parents"], ["images-folder"])
            self.assertEqual((bodies[3]["name"], bodies[3]["parents"]), ("YT-蔥爆豬肉.md", ["recipe-folder"]))
            self.assertIn("](images/step-01.jpg)", (root / ".drive" / source.name).read_text(encoding="utf-8"))
            self.assertTrue(result[0]["folder"])
            self.assertEqual(result[0]["id"], "recipe-folder")

    def test_pdf_only_upload_skips_images(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "食譜.md"
            source.write_text("# 食譜", encoding="utf-8")
            with patch.object(cloud_upload, "export_documents", return_value=[source.with_suffix(".pdf")]), \
                    patch.object(cloud_upload, "upload_files", return_value=[]) as upload, \
                    patch.object(cloud_upload, "destination_folder") as make_folder:
                cloud_upload.upload_recipe(source, ("pdf",), service=object(), progress=lambda text: None)
                make_folder.assert_not_called()
                upload.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class GoogleScopeTests(unittest.TestCase):
    def test_old_drive_file_token_triggers_new_login(self):
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        old = Credentials(token="t", refresh_token="r", client_id="c", client_secret="s",
                          token_uri="https://oauth2.googleapis.com/token",
                          scopes=["https://www.googleapis.com/auth/drive.file"])
        fresh = MagicMock()
        fresh.to_json.return_value = "{}"
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / "token.json"
            token.write_text(old.to_json(), encoding="utf-8")
            with patch.object(cloud_upload, "TOKEN_FILE", token), \
                    patch.object(cloud_upload, "ensure_client_config"), \
                    patch.object(InstalledAppFlow, "from_client_secrets_file") as factory:
                factory.return_value.run_local_server.return_value = fresh
                self.assertIs(cloud_upload.google_credentials(), fresh)
                factory.assert_called_once()
                self.assertEqual(factory.call_args.args[1], ["https://www.googleapis.com/auth/drive"])


class PlainSubtitleTests(unittest.TestCase):
    def test_vtt_srt_and_transcript_become_plain_text(self):
        from src.media import plain_subtitle_text
        vtt = ("WEBVTT\nKind: captions\nLanguage: zh-TW\n\n1\n00:00:01.000 --> 00:00:02.500 align:start\n"
               "<c>先把</c><00:00:01.500><c>豬肉切片</c>\n\n00:00:02.500 --> 00:00:04.000\n先把豬肉切片\n加入醬油&amp;米酒\n")
        self.assertEqual(plain_subtitle_text(vtt), "先把豬肉切片\n加入醬油&米酒")
        self.assertEqual(plain_subtitle_text("1\n00:00:01,000 --> 00:00:02,000\n雞蛋兩顆"), "雞蛋兩顆")
        self.assertEqual(plain_subtitle_text("[1.00 秒] 雞蛋兩顆\n[2.50 秒] 打散"), "雞蛋兩顆\n打散")

    def test_kept_subtitles_in_markdown_have_no_timestamps(self):
        from src.document_export import recipe_blocks
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
                patch.object(recipe_lens, "get_transcript", return_value="[1.00 秒] 雞蛋兩顆\n[2.00 秒] 1. 打散"),
                patch.object(recipe_lens, "interpret", return_value=RECIPE),
                patch.object(recipe_lens, "export_recipe", side_effect=export),
                patch.object(recipe_lens, "export_documents"),
            ):
                result = recipe_lens.convert_video("https://fb.watch/test", root / "out", subtitle_mode="original",
                                                   keep_subtitles=True, progress=lambda text: None)
            text = result.read_text(encoding="utf-8")
            self.assertNotIn("秒]", text)
            self.assertNotIn("-->", text)
            blocks = [value for kind, value, _ in recipe_blocks(result) if kind == "text"]
            self.assertIn("雞蛋兩顆\n1. 打散", blocks)


class CodexModelTests(unittest.TestCase):
    def test_auto_model_passes_no_model_flag(self):
        self.assertIsNone(ai_recipe.normalize_model(ai_recipe.AUTO_MODEL))
        self.assertIsNone(ai_recipe.normalize_model("  "))
        self.assertEqual(ai_recipe.normalize_model("gpt-6.1-sol"), "gpt-6.1-sol")
        self.assertNotIn("gpt-5.5", ai_recipe.AI_PROVIDERS["Codex"])

    def test_retired_or_auto_saved_model_becomes_cheapest_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"models": {"Codex": "gpt-5.5", "Claude": ai_recipe.AUTO_MODEL}}),
                            encoding="utf-8")
            models = load_settings(path)["models"]
        self.assertEqual(models["Codex"], "gpt-6-luna")
        self.assertEqual(models["Claude"], "claude-haiku-5-5")

    def test_defaults_are_cheapest_and_no_auto_option(self):
        self.assertEqual(ai_recipe.AI_PROVIDERS["Codex"][0], "gpt-6-luna")
        self.assertEqual(ai_recipe.AI_PROVIDERS["Claude"][0], "claude-haiku-5-5")
        for models in ai_recipe.AI_PROVIDERS.values():
            self.assertNotIn(ai_recipe.AUTO_MODEL, models)
        with tempfile.TemporaryDirectory() as folder:
            models = load_settings(Path(folder) / "none.json")["models"]
        self.assertEqual(models, {"Codex": "gpt-6-luna", "Claude": "claude-haiku-5-5"})

    def test_rejected_model_retries_with_explicit_fallback(self):
        rejected = ValueError('codex 執行失敗：ERROR: {"status":400,"error":{"message":"The gpt-5.5 model '
                              'is not supported when using Codex with a ChatGPT account.","code":"model_not_found"}}')
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)

            def fake_run(command, folder, prompt):
                if "--model" in command:
                    raise rejected
                (work / "recipe.json").write_text(json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
                return ""
            with patch.object(ai_recipe, "run", side_effect=fake_run) as run:
                recipe = ai_recipe.interpret_codex(work, "codex", "gpt-5.5", "提示", ["frame-00.jpg"])
        self.assertEqual(recipe["title"], "蔥爆豬肉")
        self.assertEqual(run.call_count, 2)
        # 被拒後先沿用 Codex 本身的設定（不帶 --model），即使用者原本可用的模型
        self.assertNotIn("--model", run.call_args.args[0])
        self.assertIn("--image=frame-00.jpg", run.call_args.args[0])

    def test_working_cli_default_is_used_when_selected_model_rejected(self):
        """回歸測試：原本靠 Codex 本身設定（例如 gpt-5.6-sol）可用的電腦，選 luna 被拒後要能恢復。"""
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)

            def fake_run(command, folder, prompt):
                if "--model" in command:
                    raise ValueError("model_not_found: not supported when using Codex with a ChatGPT account")
                (work / "recipe.json").write_text(json.dumps(RECIPE), encoding="utf-8")
                return ""
            with patch.object(ai_recipe, "run", side_effect=fake_run) as run:
                recipe = ai_recipe.interpret_codex(work, "codex", "gpt-6-luna", "提示", [])
        self.assertEqual(recipe["title"], "蔥爆豬肉")
        self.assertEqual(run.call_count, 2)

    def test_auto_can_fail_from_global_config_then_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)

            def fake_run(command, folder, prompt):
                if "--model" not in command:
                    raise ValueError('model_not_found: gpt-6.1-sol not supported')
                (work / "recipe.json").write_text(json.dumps(RECIPE), encoding="utf-8")
                return ""
            with patch.object(ai_recipe, "run", side_effect=fake_run) as run:
                recipe = ai_recipe.interpret_codex(work, "codex", None, "提示", [])
        self.assertEqual(recipe["title"], "蔥爆豬肉")
        self.assertEqual(run.call_count, 2)

    def test_rejected_fallback_is_bounded_and_explains_model_problem(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "run", side_effect=ValueError("model_not_found")) as run:
            with self.assertRaises(ai_recipe.CodexPlanError):
                ai_recipe.interpret_codex(Path(folder), "codex", None, "提示", [])
        # CLI 預設 → gpt-5.6-sol → gpt-6-luna → gpt-6.1-sol，各試一次
        self.assertEqual(run.call_count, 4)

    def test_luna_rejected_means_plan_not_allowed(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "run", side_effect=ValueError(
                    "The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account. model_not_found")):
            with self.assertRaises(ai_recipe.CodexPlanError) as caught:
                ai_recipe.interpret_codex(Path(folder), "codex", "gpt-6-luna", "提示", [])
        self.assertIn("版本太舊", str(caught.exception))

    def test_free_plan_falls_back_to_luna(self):
        """免費／Go 方案只能用 gpt-6-luna：被拒時依序改試，最後以 luna 成功。"""
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            models = []

            def fake_run(command, folder, prompt):
                models.append(command[command.index("--model") + 1] if "--model" in command else None)
                if models[-1] != "gpt-6-luna":
                    raise ValueError("ERROR: The model is not supported when using Codex with a ChatGPT account.")
                (work / "recipe.json").write_text(json.dumps(RECIPE), encoding="utf-8")
                return ""
            with patch.object(ai_recipe, "run", side_effect=fake_run):
                recipe = ai_recipe.interpret_codex(work, "codex", "gpt-5.6-sol", "提示", [])
        self.assertEqual(recipe["title"], "蔥爆豬肉")
        self.assertEqual(models, ["gpt-5.6-sol", None, "gpt-6-luna"])

    def test_luna_selected_is_not_retried_with_itself(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "run", side_effect=ValueError("model_not_found")) as run:
            with self.assertRaises(ValueError):
                ai_recipe.interpret_codex(Path(folder), "codex", "gpt-6-luna", "提示", [])
        self.assertEqual(run.call_count, 4)  # luna → CLI 預設 → gpt-5.6-sol → gpt-6.1-sol，不重複試 luna

    def test_other_codex_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ai_recipe, "run", side_effect=ValueError("codex 執行失敗：網路錯誤")) as run:
            with self.assertRaisesRegex(ValueError, "網路錯誤"):
                ai_recipe.interpret_codex(Path(folder), "codex", "gpt-6.1-sol", "提示", [])
        self.assertEqual(run.call_count, 1)


class ModelChoiceTests(unittest.TestCase):
    @staticmethod
    def write_auth(folder, plan):
        import base64
        claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        Path(folder, "auth.json").write_text(
            json.dumps({"tokens": {"id_token": f"header.{payload}.signature", "access_token": "x"}}),
            encoding="utf-8")

    def test_plan_is_read_from_codex_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write_auth(folder, "free")
            self.assertEqual(ai_recipe.codex_plan(folder), "free")
            self.write_auth(folder, "Pro")
            self.assertEqual(ai_recipe.codex_plan(folder), "pro")

    def test_plan_unknown_when_missing_or_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(ai_recipe.codex_plan(folder))
            Path(folder, "auth.json").write_text('{"OPENAI_API_KEY": "sk-test", "tokens": null}', encoding="utf-8")
            self.assertIsNone(ai_recipe.codex_plan(folder))

    def test_free_and_go_only_get_luna(self):
        for plan in ("free", "go", "FREE"):
            self.assertEqual(ai_recipe.model_choices("Codex", plan), ("gpt-6-luna",))
        self.assertIn("gpt-6.1-sol", ai_recipe.model_choices("Codex", "plus"))
        self.assertEqual(ai_recipe.model_choices("Codex", None)[0], "gpt-6-luna")
        self.assertEqual(ai_recipe.model_choices("Claude", "free"), ai_recipe.AI_PROVIDERS["Claude"])

    def test_labels_have_notes_and_strip_back(self):
        label = ai_recipe.model_label("gpt-6-luna")
        self.assertTrue(label.startswith("gpt-6-luna(") and label.endswith(")"))
        self.assertEqual(ai_recipe.model_id(label), "gpt-6-luna")
        self.assertEqual(ai_recipe.model_id("gpt-6.1-sol（較精準）"), "gpt-6.1-sol")
        self.assertEqual(ai_recipe.model_id(ai_recipe.AUTO_MODEL), ai_recipe.AUTO_MODEL)
        self.assertIsNone(ai_recipe.normalize_model(ai_recipe.AUTO_MODEL))
        self.assertEqual(ai_recipe.normalize_model(label), "gpt-6-luna")
        self.assertEqual(ai_recipe.model_id("my-custom-model"), "my-custom-model")


class CodexLoginTests(unittest.TestCase):
    def test_status_and_login_commands_run_hidden(self):
        done = MagicMock(returncode=0, stdout="Logged in using ChatGPT", stderr="")
        with patch.object(ai_recipe.subprocess, "run", return_value=done) as run:
            self.assertTrue(ai_recipe.codex_logged_in("codex"))
            ai_recipe.codex_login("codex")
        self.assertEqual(run.call_args_list[0].args[0], ["codex", "login", "status"])
        self.assertEqual(run.call_args_list[1].args[0], ["codex", "login"])
        for call in run.call_args_list:
            self.assertIn("creationflags", call.kwargs)
        done.returncode = 1
        with patch.object(ai_recipe.subprocess, "run", return_value=done):
            self.assertFalse(ai_recipe.codex_logged_in("codex"))

    def test_unknown_status_does_not_force_login(self):
        with patch.object(ai_recipe.subprocess, "run", side_effect=OSError("missing")):
            self.assertIsNone(ai_recipe.cli_logged_in("Codex", "codex"))
            self.assertIsNone(ai_recipe.cli_logged_in("Claude", "claude"))

    def test_convert_logs_in_codex_first_when_logged_out(self):
        with patch.object(recipe_lens, "find_tools", return_value={
                "yt-dlp": "t", "ffmpeg": "t", "ffprobe": "t", "codex": "codex", "claude": None}), \
                patch.object(recipe_lens, "cli_logged_in", return_value=False), \
                patch.object(recipe_lens, "cli_login", side_effect=ValueError("stop")) as login, \
                tempfile.TemporaryDirectory() as folder:
            messages = []
            with self.assertRaisesRegex(RuntimeError, "stop"):
                recipe_lens.convert_video("https://fb.watch/test", folder, progress=messages.append)
        login.assert_called_once_with("Codex", "codex")
        self.assertTrue(any("ChatGPT 帳號" in message for message in messages))

    def test_expired_codex_login_relogs_and_retries(self):
        expired = ValueError("codex 執行失敗：ERROR: 401 Unauthorized, please run codex login")
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            calls = []

            def fake_run(command, folder, prompt):
                calls.append(command)
                if len(calls) == 1:
                    raise expired
                (work / "recipe.json").write_text(json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
                return ""
            with patch.object(ai_recipe, "run", side_effect=fake_run), \
                    patch.object(ai_recipe, "codex_login") as login:
                recipe = ai_recipe.interpret_codex(work, "codex", None, "提示", [])
        login.assert_called_once_with("codex")
        self.assertEqual(recipe["title"], "蔥爆豬肉")

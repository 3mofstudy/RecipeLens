"""驗證自動保留路徑與雲端上傳流程。"""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from src.gui import RecipeLensApp
from src.settings import load_settings


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.folder = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.folder.name) / "settings.json"
        self.app = RecipeLensApp(self.root, settings_file=self.settings_file)
        self.recipe = Path(self.folder.name) / "食譜.md"
        self.recipe.write_text("# 食譜", encoding="utf-8")

    def tearDown(self):
        self.root.destroy()
        self.folder.cleanup()

    def test_only_current_workflow_has_upload_controls(self):
        self.assertFalse(hasattr(self.app, "upload_local"))
        self.assertFalse(hasattr(self.app, "configure_button"))
        self.assertFalse(hasattr(self.app, "upload_button"))

    def test_upload_format_checkboxes_and_select_all(self):
        self.app.select_all_formats()
        self.assertTrue(all(variable.get() for variable in self.app.cloud_formats.values()))
        self.app.url.set("https://youtu.be/test")
        self.app.upload_after.set(True)
        for variable in self.app.cloud_formats.values():
            variable.set(False)
        with patch("src.gui.messagebox.showerror") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    def test_default_subtitle_mode_is_original(self):
        self.assertEqual(self.app.subtitle_mode.get(), "original")
        self.assertEqual(str(self.app.keep_button.cget("state")), "normal")

    def test_start_button_is_large_centered_and_renamed(self):
        self.assertEqual(self.app.start_button.cget("text"), "開始下載")
        self.assertEqual(self.app.start_button.cget("style"), "Start.TButton")
        self.assertNotIn("anchor", {k: v for k, v in self.app.start_button.pack_info().items()
                                    if k == "anchor" and v != "center"})

    def test_more_settings_toggles_advanced_options(self):
        self.assertFalse(self.app.advanced.winfo_manager())
        self.app.toggle_advanced()
        self.assertEqual(self.app.advanced.winfo_manager(), "pack")
        self.app.toggle_advanced()
        self.assertFalse(self.app.advanced.winfo_manager())

    def test_default_advanced_settings(self):
        self.assertEqual(self.app.provider.get(), "Codex")
        self.assertTrue(all(variable.get() for variable in self.app.cloud_formats.values()))
        self.assertFalse(self.app.upload_after.get())
        self.assertTrue(self.app.output_dir.get())

    def test_provider_switch_updates_model_list(self):
        self.app.provider.set("Claude")
        self.app.change_provider()
        self.assertIn(self.app.model.get(), self.app.model_combo.cget("values"))
        self.assertTrue(self.app.model.get().startswith("claude") or self.app.model.get() in ("opus", "sonnet"))

    def test_login_button_only_for_claude(self):
        self.assertFalse(self.app.login_button.winfo_manager())
        self.app.provider.set("Claude")
        self.app.change_provider()
        self.assertEqual(self.app.login_button.winfo_manager(), "pack")
        with patch("src.gui.find_tool", return_value=None), patch("src.gui.messagebox.showerror") as error, \
                patch("src.gui.Thread") as thread:
            self.app.login_claude()
            error.assert_called_once()
            thread.assert_not_called()
        with patch("src.gui.claude_login") as login:
            self.app.login_worker("claude")
            login.assert_called_once_with("claude")
        self.assertEqual(self.app.events.get_nowait()[0], "logged_in")

    def test_start_passes_ai_and_output_and_saves_defaults(self):
        output = Path(self.folder.name) / "我的輸出"
        self.app.url.set("https://youtu.be/test")
        self.app.provider.set("Claude")
        self.app.change_provider()
        self.app.model.set("claude-sonnet-5-5")
        self.app.output_dir.set(str(output))
        self.app.cloud_formats["docx"].set(False)
        with patch("src.gui.Thread") as thread:
            self.app.start()
            options = thread.call_args.kwargs["args"][1]
        self.assertEqual(options["provider"], "Claude")
        self.assertEqual(options["model"], "claude-sonnet-5-5")
        self.assertEqual(options["output"], output)
        saved = load_settings(self.settings_file)
        self.assertEqual(saved["provider"], "Claude")
        self.assertEqual(saved["models"]["Claude"], "claude-sonnet-5-5")
        self.assertEqual(saved["output_dir"], str(output))
        self.assertEqual(saved["formats"], ["md", "pdf"])

    def test_relative_output_dir_is_rejected(self):
        self.app.url.set("https://youtu.be/test")
        self.app.output_dir.set("相對路徑")
        with patch("src.gui.messagebox.showerror") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    def test_local_only_does_not_require_upload_formats(self):
        self.app.url.set("https://youtu.be/test")
        for variable in self.app.cloud_formats.values():
            variable.set(False)
        with patch("src.gui.Thread") as thread:
            self.app.start()
            thread.assert_called_once()
        self.assertTrue(self.app.pending_upload["ask"])

    def test_invalid_local_filename_stops_before_download(self):
        self.app.url.set("https://youtu.be/test")
        self.app.file_name.set("CON")
        with patch("src.gui.messagebox.showerror") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    FOLDER = {"id": "f09", "name": "09.我的食譜", "path": ["我的雲端硬碟", "09.我的食譜"]}

    def test_local_path_box_removed_and_status_shows_folder(self):
        self.assertFalse(hasattr(self.app, "result_path"))
        self.app.events.put(("done", self.recipe))
        self.app.poll()
        self.assertEqual(self.app.result, self.recipe.resolve())
        self.assertIn(str(self.recipe.resolve().parent), self.app.status.get())

    def test_subfolder_field_replaced_by_drive_location(self):
        self.assertFalse(hasattr(self.app, "new_folder"))
        self.assertIn("尚未選擇", self.app.drive_location.get())
        self.app.set_drive_folder({"id": "f09", "name": "09.我的食譜", "path": [
            {"id": "root", "name": "我的雲端硬碟"}, {"id": "f09", "name": "09.我的食譜"}]})
        self.assertEqual(self.app.drive_location.get(), "我的雲端硬碟 > 09.我的食譜")
        self.assertEqual(load_settings(self.settings_file)["drive_folder"], self.FOLDER)
        reopened = RecipeLensApp(tk.Toplevel(self.root), settings_file=self.settings_file)
        self.assertEqual(reopened.drive_location.get(), "我的雲端硬碟 > 09.我的食譜")

    def test_pick_drive_folder_from_settings(self):
        service = object()
        with patch("src.gui.google_service", return_value=service):
            self.app.connect_worker("settings")
        with patch("src.gui.choose_folder", return_value={"id": "f09", "name": "09.我的食譜", "path": [
                {"id": "root", "name": "我的雲端硬碟"}, {"id": "f09", "name": "09.我的食譜"}]}) as choose:
            self.app.busy = True
            self.app.poll()
            choose.assert_called_once()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.drive_location.get(), "我的雲端硬碟 > 09.我的食譜")

    def test_start_snapshots_main_screen_settings(self):
        self.app.url.set("https://youtu.be/test")
        self.app.file_name.set("三杯雞")
        self.app.upload_after.set(True)
        self.app.select_all_formats()
        with patch("src.gui.Thread") as thread:
            self.app.start()
            self.assertEqual(thread.call_args.kwargs["args"][1]["file_stem"], "三杯雞")
        self.assertEqual(self.app.pending_upload, {"formats": ("md", "pdf", "docx"), "ask": False})

    def test_success_no_keeps_local_only(self):
        self.app.pending_upload = {"formats": ("pdf",), "ask": True}
        with patch("src.gui.ask_upload", return_value="no") as ask, patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
            ask.assert_called_once()
            connect.assert_not_called()
        self.assertIn("只保留在本機", self.app.status.get())

    def test_success_yes_uploads_directly_to_saved_folder(self):
        self.app.drive_folder = dict(self.FOLDER)
        self.app.pending_upload = {"formats": ("md", "pdf"), "ask": True}
        with patch("src.gui.ask_upload", return_value="upload"), patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
        connect.assert_called_once_with("upload", {"source": self.recipe, "formats": ("md", "pdf"), "change": False})
        service = object()
        with patch("src.gui.choose_folder") as choose, patch("src.gui.Thread") as thread:
            self.app.drive_ready("upload", connect.call_args.args[1], service)
            choose.assert_not_called()
            args = thread.call_args.kwargs["args"]
        self.assertEqual(args[3]["id"], "f09")
        self.assertEqual(self.app.drive_folder["id"], "f09")  # 記住的是根目錄，不是食譜資料夾
        self.assertEqual(args[4], {"file_stem": "食譜", "new_folder": "食譜"})

    def test_yes_without_saved_folder_opens_browser(self):
        self.app.pending_upload = {"formats": ("pdf",), "ask": True}
        with patch("src.gui.ask_upload", return_value="change"), patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
        payload = connect.call_args.args[1]
        self.assertTrue(payload["change"])
        with patch("src.gui.choose_folder", return_value=None), patch("src.gui.Thread") as thread:
            self.app.busy = True
            self.app.drive_ready("upload", payload, object())
            thread.assert_not_called()
        self.assertFalse(self.app.busy)
        self.assertIn("取消", self.app.status.get())

    def test_change_folder_then_upload_and_remember(self):
        payload = {"source": self.recipe, "formats": ("pdf",), "change": True}
        picked = {"id": "new", "name": "湯品", "path": [{"id": "r", "name": "我的雲端硬碟"}, {"id": "new", "name": "湯品"}]}
        with patch("src.gui.choose_folder", return_value=picked), patch("src.gui.Thread") as thread:
            self.app.drive_ready("upload", payload, object())
            self.assertEqual(thread.call_args.kwargs["args"][3]["id"], "new")
        self.assertEqual(load_settings(self.settings_file)["drive_folder"]["path"], ["我的雲端硬碟", "湯品"])

    def test_auto_upload_setting_skips_question(self):
        self.app.drive_folder = dict(self.FOLDER)
        self.app.pending_upload = {"formats": ("pdf",), "ask": False}
        with patch("src.gui.ask_upload") as ask, patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
            ask.assert_not_called()
            self.assertFalse(connect.call_args.args[1]["change"])

    def test_upload_worker_and_success_message(self):
        service = object()
        items = [{"id": "rf", "name": "食譜／（食譜資料夾）", "folder": True,
                  "url": "https://drive.google.com/drive/folders/rf"}, {"name": "食譜.md"}]
        with patch("src.gui.upload_recipe", return_value=items) as upload:
            self.app.upload_worker(self.recipe, ("md",), service, self.FOLDER, {"file_stem": "食譜", "new_folder": "食譜"})
            self.assertEqual(upload.call_args.kwargs["parent_id"], "f09")
        with patch("src.gui.messagebox.askyesno", return_value=True) as ask, patch("src.gui.webbrowser.open") as browser:
            self.app.poll()
            self.assertEqual(ask.call_args.args[0], "上傳成功")
            self.assertIn("我的雲端硬碟 > 09.我的食譜 > 食譜", ask.call_args.args[1])
            browser.assert_called_once_with("https://drive.google.com/drive/folders/rf")



if __name__ == "__main__":
    unittest.main(verbosity=2)

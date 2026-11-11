"""驗證自動保留路徑與雲端上傳流程。"""
from pathlib import Path
import tempfile
import time
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
import unittest
from unittest.mock import patch

from src.gui import RecipeLensApp, setup_gate
from src.settings import load_settings
from tests.qt_support import QT_APP


class GuiTests(unittest.TestCase):
    def setUp(self):
        checker = patch.object(RecipeLensApp, "request_login_status")
        checker.start()
        self.addCleanup(checker.stop)
        guard = patch("src.gui.show_setup_check",
                      side_effect=AssertionError("測試未模擬環境檢查對話窗"))
        guard.start()
        self.addCleanup(guard.stop)
        login_guard = patch("src.gui.LoginWaitDialog",
                            side_effect=AssertionError("測試未模擬登入等待視窗"))
        login_guard.start()
        self.addCleanup(login_guard.stop)
        self.qt = QT_APP
        self.folder = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.folder.name) / "settings.json"
        self.app = RecipeLensApp(settings_file=self.settings_file)
        self.recipe = Path(self.folder.name) / "食譜.md"
        self.recipe.write_text("# 食譜", encoding="utf-8")

    def tearDown(self):
        self.app.set_busy(False)
        self.app.close()
        self.app.deleteLater()
        self.qt.processEvents()
        self.folder.cleanup()

    def test_only_current_workflow_has_upload_controls(self):
        self.assertFalse(hasattr(self.app, "upload_local"))
        self.assertFalse(hasattr(self.app, "configure_button"))
        self.assertFalse(hasattr(self.app, "upload_button"))

    def test_upload_format_checkboxes_and_select_all(self):
        self.app.select_all_formats()
        self.assertTrue(all(variable.isChecked() for variable in self.app.cloud_formats.values()))
        for variable in self.app.cloud_formats.values():
            variable.setChecked(False)
        # 勾選上傳卻沒勾格式：按開始時就擋下，不開始轉換
        self.app.url.setText("https://youtu.be/test")
        self.app.drive_folder = dict(self.FOLDER)
        self.app.upload_after.setChecked(True)
        with patch("src.gui.show_error") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    def test_default_subtitle_mode_is_original(self):
        self.assertEqual(self.app.subtitle_mode(), "original")
        self.assertTrue(self.app.keep.isEnabled())

    def test_last_url_is_restored_even_without_starting(self):
        self.assertEqual(self.app.url.text(), "")
        self.app.url.setText("https://www.youtube.com/watch?v=previous")
        self.app.close()
        reopened = RecipeLensApp(settings_file=self.settings_file)
        try:
            self.assertEqual(reopened.url.text(), "https://www.youtube.com/watch?v=previous")
            self.assertEqual(reopened.platform.currentText(), "YouTube")
            reopened.url.clear()
            reopened.url.editingFinished.emit()
            self.assertEqual(load_settings(self.settings_file)["last_url"], "")
        finally:
            reopened.close()
            reopened.deleteLater()

    def test_start_button_is_large_and_prominent(self):
        self.assertEqual(self.app.start_button.text(), '開始下載')
        self.assertEqual(self.app.start_button.objectName(), 'primary')
        self.assertGreaterEqual(self.app.start_button.minimumWidth(), 200)

    def test_stop_waits_for_worker_and_skips_recovery_and_upload(self):
        self.assertFalse(self.app.stop_button.isEnabled())
        self.app.set_busy(True)
        self.assertTrue(self.app.stop_button.isEnabled())
        self.app.pending_upload = {"formats": ("md",)}
        self.app.stop_button.click()
        self.assertTrue(self.app.busy)
        self.assertFalse(self.app.start_button.isEnabled())
        self.assertFalse(self.app.stop_button.isEnabled())
        self.app.events.put(("progress", "遲到的進度"))
        self.app.poll()
        self.assertTrue(self.app.busy)
        with patch.object(self.app, "finish_error") as recovery:
            self.app.events.put(("error", "已停止工具"))
            self.app.poll()
            recovery.assert_not_called()
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.pending_upload)
        self.assertIn("已中止", self.app.status.text())
        self.assertTrue(self.app.start_button.isEnabled())

    def test_stuck_cancel_offers_force_quit(self):
        self.app.set_busy(True)
        with patch("src.gui.kill_active_processes") as kill:
            self.app.stop()
            kill.assert_called_once()
        self.assertFalse(self.app.stop_button.isEnabled())
        self.app.offer_force_stop()
        self.assertTrue(self.app.stop_button.isEnabled())
        self.assertEqual(self.app.stop_button.text(), "強制結束")
        with patch("src.gui.ask_yes_no", return_value=False), patch.object(self.app, "force_quit") as force:
            self.app.stop_button.click()
            force.assert_not_called()
        with patch("src.gui.ask_yes_no", return_value=True), patch.object(self.app, "force_quit") as force:
            self.app.stop_button.click()
            force.assert_called_once()
        self.app.set_busy(False)

    def test_cancelled_worker_does_not_start_conversion(self):
        self.app.set_busy(True)
        self.app.stop()
        with patch("src.gui.convert_video") as convert:
            self.app.worker("https://youtu.be/test", {})
            convert.assert_not_called()
        self.app.poll()
        self.assertFalse(self.app.busy)

    def test_more_settings_toggles_advanced_options(self):
        self.assertTrue(self.app.advanced.isHidden())
        self.app.more_button.click()
        self.assertFalse(self.app.advanced.isHidden())
        self.app.more_button.click()
        self.assertTrue(self.app.advanced.isHidden())

    def test_expanding_advanced_scrolls_to_bottom(self):
        self.app.resize(980, 680)
        self.app.show()
        QTest.qWait(50)
        scrollbar = self.app.input_scroll.verticalScrollBar()
        scrollbar.setValue(0)
        self.app.more_button.click()
        QTest.qWait(50)
        self.assertGreater(scrollbar.maximum(), 0)
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_default_advanced_settings(self):
        self.assertEqual(self.app.provider.currentText(), "Codex")
        self.assertTrue(all(variable.isChecked() for variable in self.app.cloud_formats.values()))
        self.assertFalse(self.app.upload_after.isChecked())
        self.assertTrue(self.app.output_dir.text())

    def test_provider_switch_updates_model_list(self):
        self.app.provider.setCurrentText("Claude")
        self.app.change_provider()
        self.assertIn(self.app.model.currentText(), [self.app.model.itemText(i) for i in range(self.app.model.count())])
        from src.ai_recipe import AI_PROVIDERS, model_label
        items = [self.app.model.itemText(i) for i in range(self.app.model.count())]
        self.assertEqual(items, [model_label(name) for name in AI_PROVIDERS["Claude"]])

    def test_login_button_follows_selected_provider(self):
        self.assertFalse(self.app.login_button.isHidden())
        self.assertEqual(self.app.login_button.text(), "登入 Codex 帳號")
        self.app.provider.setCurrentText("Claude")
        self.app.change_provider()
        self.assertEqual(self.app.login_button.text(), "登入 Claude 帳號")
        # 找不到 AI 時改開環境檢查畫面（模擬，避免測試中出現會卡住的對話窗）
        with patch("src.gui.find_tool", return_value=None), \
                patch.object(self.app, "check_setup") as check, patch("src.gui.Thread") as thread:
            self.app.login_ai()
            check.assert_called_once_with()
            thread.assert_not_called()
        for provider, tool in (("Codex", "codex"), ("Claude", "claude")):
            with patch("src.gui.cli_login") as login:
                self.app.login_worker(provider, tool)
                login.assert_called_once_with(provider, tool)
            self.assertEqual(self.app.events.get_nowait(), ("logged_in", provider))

    def test_login_status_updates_only_matching_provider(self):
        for provider in ("Codex", "Claude"):
            self.app.provider.setCurrentText(provider)
            with patch("src.gui.find_tool", return_value="mock-cli"), \
                    patch("src.gui.cli_logged_in", return_value=True) as check:
                self.app.login_status_worker(provider, self.app.login_checks[provider])
                check.assert_called_once_with(provider, "mock-cli")
            self.app.poll()
            self.assertEqual(self.app.login_button.text(), f"已登入 {provider}")
            for state in (False, None):
                self.app.events.put(("login_status", (provider, self.app.login_checks[provider], state)))
                self.app.poll()
                self.assertEqual(self.app.login_button.text(), f"登入 {provider} 帳號")
        self.app.events.put(("login_status", ("Codex", self.app.login_checks["Codex"], True)))
        self.app.poll()
        self.assertEqual(self.app.login_button.text(), "登入 Claude 帳號")
        self.app.events.put(("logged_in", "Claude"))
        self.app.poll()
        self.assertEqual(self.app.login_button.text(), "已登入 Claude")
        self.app.events.put(("login_status", ("Claude", self.app.login_checks["Claude"] - 1, False)))
        self.app.poll()
        self.assertEqual(self.app.login_button.text(), "已登入 Claude")

    def test_startup_checks_codex_first(self):
        with patch.object(RecipeLensApp, "request_login_status") as check:
            reopened = RecipeLensApp(settings_file=self.settings_file)
            try:
                self.assertEqual(check.call_args_list[0].args, ("Codex",))
            finally:
                reopened.close()
                reopened.deleteLater()

    def test_codex_login_button_opens_browser_login(self):
        with patch("src.gui.find_tool", return_value="codex"), patch("src.gui.Thread") as thread, \
                patch("src.gui.LoginWaitDialog") as dialog:
            # 模擬登入成功：exec 期間發出 accepted 訊號
            dialog.return_value.exec.side_effect = lambda: dialog.return_value.accepted.connect.call_args.args[0]()
            self.app.login_ai()
        provider, tool, cancel = thread.call_args.kwargs["args"]
        self.assertEqual((provider, tool), ("Codex", "codex"))
        self.assertFalse(cancel.is_set())
        self.assertFalse(self.app.busy)  # 登入不鎖定主畫面

    def test_closing_login_window_cancels_and_returns_to_main(self):
        with patch("src.gui.find_tool", return_value="codex"), patch("src.gui.Thread") as thread, \
                patch("src.gui.LoginWaitDialog") as dialog, patch("src.gui.show_error") as error, \
                patch("src.gui.ask_yes_no") as ask:
            dialog.return_value.exec.return_value = 0  # 使用者按取消或關閉視窗，沒有 accepted
            self.app.login_ai()
            cancel = thread.call_args.kwargs["args"][2]
            self.assertTrue(cancel.is_set())
            self.assertFalse(self.app.busy)
            self.assertIn("已取消", self.app.status.text())
            # 背景登入程式結束後回報的失敗不再顯示，也不詢問自動修復
            self.app.events.put(("login_failed", ("Codex", "Codex 登入未完成。")))
            self.app.poll()
            error.assert_not_called()
            ask.assert_not_called()

    def test_login_failure_shows_error_without_repair(self):
        self.app.login_cancel = None
        with patch("src.gui.show_error") as error, patch("src.gui.ask_yes_no") as ask:
            self.app.events.put(("login_failed", ("Codex", "Error logging in: os error 10013")))
            self.app.poll()
            error.assert_called_once()
            ask.assert_not_called()
        self.assertFalse(self.app.busy)

    def test_login_worker_stops_when_cancelled(self):
        from threading import Event
        from src.cancellation import check_cancelled
        cancel = Event()
        cancel.set()
        with patch("src.gui.cli_login", side_effect=lambda *a: check_cancelled()):
            self.app.login_worker("Codex", "codex", cancel)
        self.assertEqual(self.app.events.get_nowait(), ("login_cancelled", "Codex"))

    def test_start_passes_ai_and_output_and_saves_defaults(self):
        output = Path(self.folder.name) / "我的輸出"
        self.app.url.setText("https://youtu.be/test")
        self.app.provider.setCurrentText("Claude")
        self.app.change_provider()
        self.app.model.setCurrentText("claude-sonnet-5-5")
        self.app.output_dir.setText(str(output))
        self.app.cloud_formats["docx"].setChecked(False)
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

    def test_browsed_output_dir_is_remembered_immediately(self):
        output = Path(self.folder.name) / "中文輸出"
        with patch("src.gui.QFileDialog.getExistingDirectory", return_value=str(output)):
            self.app.browse_output()
        self.assertEqual(load_settings(self.settings_file)["output_dir"], str(output))
        reopened = RecipeLensApp(settings_file=self.settings_file)
        self.addCleanup(reopened.deleteLater)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.output_dir.text(), str(output))

    def test_typed_relative_output_dir_is_not_saved(self):
        before = load_settings(self.settings_file)["output_dir"]
        self.app.output_dir.setText("相對路徑")
        self.app.remember_output()
        self.assertEqual(load_settings(self.settings_file)["output_dir"], before)

    def test_first_launch_always_shows_setup_gate(self):
        with patch("src.gui.show_setup_check", return_value="enter") as dialog:
            self.assertTrue(setup_gate(self.settings_file, lambda: {"Codex": True, "Claude": False}))
            dialog.assert_called_once()
            self.assertTrue(dialog.call_args.kwargs["gate"])
        self.assertTrue(load_settings(self.settings_file)["setup_done"])
        # 已通過且仍有一種 AI：之後直接進主畫面
        with patch("src.gui.show_setup_check") as dialog:
            self.assertTrue(setup_gate(self.settings_file, lambda: {"Codex": True, "Claude": False}))
            dialog.assert_not_called()

    def test_gate_blocks_until_one_installed(self):
        # 兩種都沒裝時即使收到「進入」也不放行（按鈕本身亦停用）
        with patch("src.gui.show_setup_check", return_value="enter"):
            self.assertFalse(setup_gate(self.settings_file, lambda: {"Codex": False, "Claude": False}))
        self.assertFalse(load_settings(self.settings_file)["setup_done"])

    def test_gate_recheck_then_enter(self):
        statuses = iter([{"Codex": False, "Claude": False}, {"Codex": True, "Claude": False}])
        actions = iter(["recheck", "enter"])
        with patch("src.gui.show_setup_check", side_effect=lambda *a, **k: next(actions)) as dialog:
            self.assertTrue(setup_gate(self.settings_file, lambda: next(statuses)))
            self.assertEqual(dialog.call_count, 2)

    def test_gate_quit_and_reappears_when_all_uninstalled(self):
        with patch("src.gui.show_setup_check", return_value="quit"):
            self.assertFalse(setup_gate(self.settings_file, lambda: {"Codex": False, "Claude": False}))
        settings = load_settings(self.settings_file)
        settings["setup_done"] = True
        from src.settings import save_settings
        save_settings(settings, self.settings_file)
        with patch("src.gui.show_setup_check", return_value="quit") as dialog:
            self.assertFalse(setup_gate(self.settings_file, lambda: {"Codex": False, "Claude": False}))
            dialog.assert_called_once()

    def test_manual_check_recheck_requests_login(self):
        statuses = iter([{"Codex": False, "Claude": False}, {"Codex": True, "Claude": True}])
        actions = iter(["recheck", "close"])
        with patch("src.gui.ai_tool_status", side_effect=lambda: next(statuses)), \
                patch("src.gui.show_setup_check", side_effect=lambda *a, **k: next(actions)), \
                patch.object(self.app, "request_login_status") as login:
            self.app.check_setup()
            self.assertEqual({call.args[0] for call in login.call_args_list}, {"Codex", "Claude"})
        self.assertIn("setup_done", self.app.current_settings())

    def test_login_without_cli_opens_setup_check(self):
        with patch("src.gui.find_tool", return_value=None), \
                patch.object(self.app, "check_setup") as check:
            self.app.login_ai()
            check.assert_called_once_with()

    def test_free_plan_shows_only_luna(self):
        self.app.provider.setCurrentText("Codex")
        self.app.change_provider()
        self.app.set_codex_plan("free")
        items = [self.app.model.itemText(i) for i in range(self.app.model.count())]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].startswith("gpt-6-luna("))
        self.assertFalse(self.app.model.isEditable())
        self.assertEqual(self.app.selected_model(), "gpt-6-luna")
        self.assertFalse(self.app.plan_hint.isHidden())
        self.assertEqual(self.app.current_settings()["models"]["Codex"], "gpt-6-luna")

    def test_paid_plan_shows_annotated_models(self):
        self.app.provider.setCurrentText("Codex")
        self.app.change_provider()
        self.app.set_codex_plan("pro")
        items = [self.app.model.itemText(i) for i in range(self.app.model.count())]
        self.assertGreater(len(items), 1)
        self.assertTrue(any(item.startswith("gpt-6.1-sol(") for item in items))
        self.assertTrue(self.app.model.isEditable())
        self.app.model.setCurrentIndex(next(i for i, t in enumerate(items) if t.startswith("gpt-6.1-terra(")))
        self.assertEqual(self.app.selected_model(), "gpt-6.1-terra")

    def test_plan_does_not_affect_claude(self):
        self.app.set_codex_plan("free")
        self.app.provider.setCurrentText("Claude")
        self.app.change_provider()
        self.assertGreater(self.app.model.count(), 1)
        self.assertTrue(self.app.plan_hint.isHidden())

    def test_relative_output_dir_is_rejected(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.output_dir.setText("相對路徑")
        with patch("src.gui.show_error") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    def test_local_only_does_not_require_upload_formats(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.upload_after.setChecked(False)
        for variable in self.app.cloud_formats.values():
            variable.setChecked(False)
        with patch("src.gui.Thread") as thread:
            self.app.start()
            thread.assert_called_once()
        self.assertIsNone(self.app.pending_upload)

    def test_upload_requires_folder_chosen_before_start(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.drive_folder = None
        self.app.upload_after.setChecked(True)
        with patch("src.gui.show_error") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            self.assertIn("選擇", error.call_args.args[1])
            thread.assert_not_called()

    def test_invalid_local_filename_stops_before_download(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.file_name.setText("CON")
        with patch("src.gui.show_error") as error, patch("src.gui.Thread") as thread:
            self.app.start()
            error.assert_called_once()
            thread.assert_not_called()

    FOLDER = {"id": "f09", "name": "09.我的食譜", "path": ["我的雲端硬碟", "09.我的食譜"]}

    def test_completed_recipe_shows_preview_and_local_path(self):
        self.assertEqual(self.app.result_path.text(), "")
        self.app.events.put(("done", self.recipe))
        self.app.poll()
        self.assertEqual(self.app.result, self.recipe.resolve())
        self.assertIn(str(self.recipe.resolve().parent), self.app.status.text())
        self.assertEqual(self.app.result_path.text(), str(self.recipe.resolve()))
        self.assertIn("食譜", self.app.preview.toPlainText())
        self.assertEqual(self.app.preview_stack.currentIndex(), 1)
        self.assertTrue(self.app.open_folder_button.isEnabled())
        self.assertFalse(self.app.file_buttons["pdf"].isEnabled())

    def test_subtitle_click_reveals_language_and_resets_keep(self):
        self.app.keep.setChecked(True)
        self.app.subtitle_buttons["none"].click()
        self.assertEqual(self.app.subtitle_mode(), "none")
        self.assertFalse(self.app.speech_row.isHidden())
        self.assertFalse(self.app.keep.isChecked())
        self.assertFalse(self.app.keep.isEnabled())
        self.app.speech_language.setCurrentText("閩南語")
        self.assertIn("需核對", self.app.speech_note.text())
        self.app.subtitle_buttons["original"].click()
        self.assertTrue(self.app.speech_row.isHidden())
        self.assertTrue(self.app.keep.isEnabled())

    def test_busy_locks_settings_and_prevents_close(self):
        self.app.set_busy(True)
        self.assertFalse(self.app.input_panel.isEnabled())
        self.assertFalse(self.app.start_button.isEnabled())
        self.assertEqual(self.app.progress.maximum(), 0)
        with patch("src.gui.ask_yes_no", return_value=False) as ask, \
                patch.object(self.app, "force_quit") as force:
            self.assertFalse(self.app.close())
            ask.assert_called_once()
            force.assert_not_called()
        with patch("src.gui.ask_yes_no", return_value=True), patch.object(self.app, "force_quit") as force:
            self.assertFalse(self.app.close())
            force.assert_called_once()
        self.app.set_busy(False)
        self.assertTrue(self.app.input_panel.isEnabled())

    def test_background_result_is_delivered_by_qt_timer(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.output_dir.setText(self.folder.name)
        self.assertTrue(self.app.local_formats["md"].isChecked())
        self.assertFalse(self.app.local_formats["md"].isEnabled())
        self.app.local_formats["pdf"].setChecked(False)
        self.app.local_formats["docx"].setChecked(False)
        with patch("src.gui.convert_video", return_value=self.recipe) as convert, \
                patch.object(self.app, "connect"):
            self.app.start_button.click()
            deadline = time.monotonic() + 3
            while self.app.busy and time.monotonic() < deadline:
                QTest.qWait(20)
            self.assertFalse(self.app.busy)
            convert.assert_called_once()
            self.assertEqual(convert.call_args.kwargs["local_formats"], ("md",))
            self.assertEqual(load_settings(self.settings_file)["local_formats"], ["md"])
            self.assertEqual(self.app.result, self.recipe.resolve())
            self.assertEqual(self.app.preview_stack.currentIndex(), 1)

    def test_failed_background_work_unlocks_ui_and_clears_pending_upload(self):
        self.app.set_busy(True)
        self.app.pending_upload = {"formats": ("pdf",)}
        with patch("src.gui.convert_video", side_effect=RuntimeError("下載失敗")), \
                patch("src.gui.ask_yes_no", return_value=False), \
                patch("src.gui.show_error") as error:
            self.app.worker("https://youtu.be/test", {})
            self.app.poll()
            self.assertFalse(self.app.busy)
            self.assertIsNone(self.app.pending_upload)
            self.assertTrue(self.app.start_button.isEnabled())
            self.assertIn("下載失敗", error.call_args.args[1])

    def test_failed_repair_reports_without_second_consent(self):
        self.app.repair_selected = True
        self.app.recovery_asked = True
        with patch("src.gui.show_error"), patch("src.gui.ask_yes_no") as ask, \
                patch("src.gui.Thread") as thread:
            self.app.finish_error("usage limit reached")
            ask.assert_not_called()
            self.assertEqual(thread.call_args.kwargs["target"], self.app.report_worker)
            self.assertIn("usage limit", thread.call_args.kwargs["args"][0])
            self.assertIsNone(self.app.pending_upload)

    def test_declined_repair_asks_before_report(self):
        self.app.recovery_asked = True
        with patch("src.gui.show_error"), patch("src.gui.ask_yes_no", return_value=False) as ask, \
                patch("src.gui.Thread") as thread:
            self.app.finish_error("failed")
            self.assertEqual(ask.call_args.args[0], "是否回報錯誤")
            thread.assert_not_called()

    def test_plan_error_stops_without_repair_or_report(self):
        from src.ai_recipe import CodexPlanError
        self.app.reset_recovery()
        with patch.object(self.app, "request_repair") as ask_repair:
            self.assertFalse(self.app.recover(CodexPlanError("方案不支援"), "AI 判讀"))
            ask_repair.assert_not_called()
        with patch("src.gui.show_error") as error, patch("src.gui.ask_yes_no") as ask, \
                patch("src.gui.Thread") as thread:
            self.app.finish_error("方案不支援")
            error.assert_called_once()
            ask.assert_not_called()
            thread.assert_not_called()

    def test_quota_recovery_stops_without_ai_calls(self):
        with patch.object(self.app, "request_repair", return_value=True), \
                patch("src.recovery.run") as ai:
            self.assertFalse(self.app.recover(ValueError("usage limit reached"), "AI 判讀"))
            self.assertTrue(self.app.repair_selected)
            ai.assert_not_called()

    def test_report_failure_is_not_retried(self):
        with patch("src.gui.send_report", side_effect=ValueError("webhook failed")) as send, \
                patch("src.gui.show_error"), patch("src.gui.ask_yes_no") as ask:
            self.app.report_worker("report")
            self.app.poll()
            send.assert_called_once()
            ask.assert_not_called()
            self.assertIn("送出失敗", self.app.status.text())

    def test_background_quota_failure_sends_report_after_one_consent(self):
        def convert(url, *, on_error, **options):
            error = ValueError("usage limit reached")
            self.assertFalse(on_error(error, "AI 判讀"))
            raise error

        self.app.url.setText("https://youtu.be/test")
        self.app.output_dir.setText(self.folder.name)
        with patch("src.gui.convert_video", side_effect=convert), \
                patch("src.gui.ask_yes_no", return_value=True) as ask, \
                patch("src.gui.show_error"), patch("src.gui.send_report") as send:
            self.app.start()
            deadline = time.monotonic() + 3
            while self.app.busy and time.monotonic() < deadline:
                QTest.qWait(20)
            self.assertFalse(self.app.busy)
            ask.assert_called_once()
            self.assertEqual(ask.call_args.args[0], "是否自動修復")
            send.assert_called_once()
            self.assertIn("額度", send.call_args.args[0])
            self.assertIsNone(self.app.pending_upload)

    def test_preview_resources_are_local_and_confined_to_recipe(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QTextDocument
        image = QImage(800, 400, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        target = self.recipe.parent / "step.png"
        image.save(str(target))
        self.recipe.write_text("# 食譜\n\n![步驟](step.png)", encoding="utf-8")
        self.app.preview.show_recipe(self.recipe)
        kind = QTextDocument.ResourceType.ImageResource
        resource = self.app.preview.loadResource(kind, QUrl("step.png"))
        self.assertLessEqual(resource.width(), 440)
        self.assertIsNone(self.app.preview.loadResource(kind, QUrl("https://example.com/image.png")))
        self.assertIsNone(self.app.preview.loadResource(kind, QUrl("../outside.png")))

    def test_open_files_uses_current_recipe(self):
        self.app.result = self.recipe
        with patch("src.gui.QDesktopServices.openUrl", return_value=True) as open_url:
            self.app.open_document("pdf")
            open_url.assert_not_called()
            self.app.open_document("md")
            self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), self.recipe)

    def test_subfolder_field_replaced_by_drive_location(self):
        self.assertFalse(hasattr(self.app, "new_folder"))
        self.assertIn("尚未選擇", self.app.drive_location.text())
        self.app.set_drive_folder({"id": "f09", "name": "09.我的食譜", "path": [
            {"id": "root", "name": "我的雲端硬碟"}, {"id": "f09", "name": "09.我的食譜"}]})
        self.assertEqual(self.app.drive_location.text(), "我的雲端硬碟 > 09.我的食譜")
        self.assertEqual(load_settings(self.settings_file)["drive_folder"], self.FOLDER)
        reopened = RecipeLensApp(settings_file=self.settings_file)
        self.assertEqual(reopened.drive_location.text(), "我的雲端硬碟 > 09.我的食譜")
        reopened.close()

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
        self.assertEqual(self.app.drive_location.text(), "我的雲端硬碟 > 09.我的食譜")

    def test_start_snapshots_main_screen_settings(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.file_name.setText("三杯雞")
        self.app.drive_folder = dict(self.FOLDER)
        self.app.upload_after.setChecked(True)
        self.app.select_all_formats()
        with patch("src.gui.Thread") as thread:
            self.app.start()
            self.assertEqual(thread.call_args.kwargs["args"][1]["file_stem"], "三杯雞")
        self.assertEqual(self.app.pending_upload, {"formats": ("md", "pdf", "docx")})
        self.assertTrue(load_settings(self.settings_file)["auto_upload"])

    def test_change_folder_then_upload_and_remember(self):
        payload = {"source": self.recipe, "formats": ("pdf",), "change": True}
        picked = {"id": "new", "name": "湯品", "path": [{"id": "r", "name": "我的雲端硬碟"}, {"id": "new", "name": "湯品"}]}
        with patch("src.gui.choose_folder", return_value=picked), patch("src.gui.Thread") as thread:
            self.app.drive_ready("upload", payload, object())
            self.assertEqual(thread.call_args.kwargs["args"][3]["id"], "new")
        self.assertEqual(load_settings(self.settings_file)["drive_folder"]["path"], ["我的雲端硬碟", "湯品"])

    def test_upload_worker_and_success_message(self):
        service = object()
        items = [{"id": "rf", "name": "食譜／（食譜資料夾）", "folder": True,
                  "url": "https://drive.google.com/drive/folders/rf"}, {"name": "食譜.md"}]
        with patch("src.gui.upload_recipe", return_value=items) as upload:
            self.app.upload_worker(self.recipe, ("md",), service, self.FOLDER, {"file_stem": "食譜", "new_folder": "食譜"})
            self.assertEqual(upload.call_args.kwargs["parent_id"], "f09")
        with patch("src.gui.ask_yes_no", return_value=True) as ask, patch("src.gui.webbrowser.open") as browser:
            self.app.poll()
            self.assertEqual(ask.call_args.args[0], "上傳成功")
            self.assertIn("我的雲端硬碟 > 09.我的食譜 > 食譜", ask.call_args.args[1])
            browser.assert_called_once_with("https://drive.google.com/drive/folders/rf")

    def test_done_uploads_to_preselected_folder_without_asking(self):
        """按開始前已選好資料夾：轉換完成直接上傳，不跳詢問也不開資料夾視窗。"""
        self.app.drive_folder = dict(self.FOLDER)
        self.app.pending_upload = {"formats": ("md", "pdf")}
        with patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
        connect.assert_called_once_with("upload", {"source": self.recipe, "formats": ("md", "pdf"), "change": False})
        with patch("src.gui.choose_folder") as choose, patch("src.gui.Thread") as thread:
            self.app.drive_ready("upload", connect.call_args.args[1], object())
            choose.assert_not_called()
            args = thread.call_args.kwargs["args"]
        self.assertEqual(args[3]["id"], "f09")
        self.assertEqual(args[4], {"file_stem": "食譜", "new_folder": "食譜"})

    def test_picking_drive_folder_never_starts_conversion(self):
        service = object()
        with patch("src.gui.google_service", return_value=service):
            self.app.connect_worker("settings")
        with patch("src.gui.choose_folder", return_value={"id": "f09", "name": "09.我的食譜", "path": [
                {"id": "root", "name": "我的雲端硬碟"}, {"id": "f09", "name": "09.我的食譜"}]}), \
                patch.object(self.app, "worker") as worker, patch("src.gui.convert_video") as convert:
            self.app.busy = True
            self.app.poll()
            worker.assert_not_called()
            convert.assert_not_called()
        self.assertIsNone(self.app.pending_upload)

    def test_cancel_folder_browser_keeps_local_only(self):
        payload = {"source": self.recipe, "formats": ("pdf",), "change": True}
        with patch("src.gui.choose_folder", return_value=None), patch("src.gui.Thread") as thread:
            self.app.busy = True
            self.app.drive_ready("upload", payload, object())
            thread.assert_not_called()
        self.assertFalse(self.app.busy)
        self.assertIn("取消", self.app.status.text())

    def test_unchecked_upload_keeps_local(self):
        self.app.url.setText("https://youtu.be/test")
        self.app.upload_after.setChecked(False)
        with patch("src.gui.Thread"):
            self.app.start()
        self.assertIsNone(self.app.pending_upload)
        with patch.object(self.app, "connect") as connect:
            self.app.events.put(("done", self.recipe))
            self.app.poll()
            connect.assert_not_called()

    def test_old_settings_migrate_to_auto_upload(self):
        self.settings_file.write_text('{"upload_after": true}', encoding="utf-8")
        reopened = RecipeLensApp(settings_file=self.settings_file)
        self.assertFalse(reopened.upload_after.isChecked())  # 舊 upload_after 不沿用
        reopened.close()
        import json
        self.settings_file.write_text(json.dumps({"ask_upload": True, "drive_folder": self.FOLDER}), encoding="utf-8")
        self.assertTrue(load_settings(self.settings_file)["auto_upload"])
        self.settings_file.write_text('{"ask_upload": true}', encoding="utf-8")
        self.assertFalse(load_settings(self.settings_file)["auto_upload"])  # 沒選過資料夾不自動上傳




if __name__ == "__main__":
    unittest.main(verbosity=2)

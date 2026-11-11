"""PySide6 主視窗：沿用既有處理流程，透過佇列將背景結果交回 Qt。"""
from pathlib import Path
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Event, Thread
import os
import sys
import webbrowser
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMainWindow
from .ai_recipe import (AI_PROVIDERS, CodexPlanError, PLAN_NAMES, PROVIDER_TOOLS, FREE_CODEX_MODEL, cli_login,
                        cli_logged_in, codex_plan, is_free_codex_plan, model_choices, model_id, model_label)
from .environment import find_tool
from .recipe_lens import DEFAULT_OUTPUT, convert_video
from .media import kill_active_processes
from .settings import SETTINGS_FILE, UPLOAD_FORMATS, load_settings, save_settings
from .video_download import detect_platform
from .cloud_upload import google_service, upload_recipe
from .drive_browser import choose_folder
from .document_export import validate_filename
from .qt_window import (WindowUi, ASSETS, format_location, show_error, show_info,
                        ask_yes_no, show_setup_check, LoginWaitDialog)
from .setup_check import ai_tool_status, any_installed
from .qt_style import apply_style
from .recovery import diagnose, error_text, perform, report_body, send_report, REPORT_TARGET
from .cancellation import JobCancelled, cancel_scope, cancellable_worker, check_cancelled


class RecipeLensApp(QMainWindow, WindowUi):
    def __init__(self, parent=None, settings_file=SETTINGS_FILE):
        super().__init__(parent)
        self.events = Queue()
        self.busy = False
        self.cancel_event = Event()
        self.login_states = {}
        self.login_checks = {provider: 0 for provider in AI_PROVIDERS}
        self.result = None
        self.pending_upload = None
        self.repair_selected = False
        self.recovery_asked = False
        self.error_stage = "準備工作"
        self.recovery_notes = []
        self.job_provider = "Codex"
        self.job_model = None
        self.settings_file = settings_file
        settings = load_settings(settings_file)
        self.models = dict(settings['models'])
        self.active_provider = settings['provider']
        self.job_provider = self.active_provider
        self.drive_folder = settings['drive_folder']
        self.drive_service = None
        self.setWindowTitle('RecipeLens · 影片變食譜')
        self.setWindowIcon(QIcon(str(ASSETS / 'recipelens.ico')))
        self.resize(1220, 860)
        self.setMinimumSize(980, 680)
        self.codex_plan = None
        self.plan_blocked = False
        self.login_dialog = None
        self.login_cancel = None
        self.build_ui(settings)
        self.fill_models()
        self.url.setText(settings["last_url"])
        self.url.editingFinished.connect(self.remember_url)
        self.output_dir.editingFinished.connect(self.remember_output)
        self.update_subtitles()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.request_login_status("Codex")
        if self.active_provider != "Codex":
            self.request_login_status(self.active_provider)

    def subtitle_mode(self):
        return next(mode for mode, item in self.subtitle_buttons.items() if item.isChecked())

    def toggle_advanced(self):
        opened = self.advanced.isHidden()
        self.advanced.setVisible(opened)
        self.more_button.setText('進階設定　－' if opened else '進階設定　＋')
        if opened:
            QTimer.singleShot(0, self.scroll_to_advanced_bottom)

    def scroll_to_advanced_bottom(self):
        if not self.advanced.isHidden():
            self.input_panel.layout().activate()
            scrollbar = self.input_scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def toggle_log(self):
        self.log.setVisible(self.log.isHidden())

    def paste(self):
        self.url.setText(QApplication.clipboard().text().strip())

    def detect(self, *_):
        try:
            self.platform.setCurrentText(detect_platform(self.url.text().strip()))
        except ValueError:
            pass

    def update_subtitles(self, *_):
        mode = self.subtitle_mode()
        self.speech_row.setVisible(mode == 'none')
        self.keep.setEnabled(mode == 'original')
        if mode != 'original':
            self.keep.setChecked(False)
        self.update_speech_note()

    def update_speech_note(self, *_):
        notes = {'其他': '自動偵測影片語言。', '粵語': '首次使用會下載較大的語音模型。',
                 '閩南語': '以中文辨識與台語提示輔助，結果需核對；首次會下載較大模型。'}
        text = notes.get(self.speech_language.currentText(), '') if self.subtitle_mode() == 'none' else ''
        self.speech_note.setText(text)
        self.speech_note.setVisible(bool(text))

    def change_provider(self, *_):
        self.models[self.active_provider] = self.selected_model()
        self.active_provider = self.provider.currentText()
        self.fill_models()
        self.update_login_button()
        self.request_login_status(self.active_provider)

    def selected_model(self):
        """目前選擇的模型名稱（去掉註腳）。"""
        return model_id(self.model.currentText())

    def fill_models(self):
        """依平台與 ChatGPT 方案填入模型清單；免費／Go 方案只顯示 gpt-6-luna 且不可修改。"""
        provider = self.active_provider
        choices = model_choices(provider, self.codex_plan if provider == "Codex" else None)
        free = provider == "Codex" and is_free_codex_plan(self.codex_plan)
        saved = FREE_CODEX_MODEL if free else (self.models.get(provider) or choices[0])
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems([model_label(name) for name in choices])
        self.model.setEditable(not free)
        index = self.model.findText(model_label(saved))
        if index >= 0:
            self.model.setCurrentIndex(index)
        else:
            self.model.setEditText(saved)  # 自行輸入的清單外模型
        self.model.blockSignals(False)
        if provider == "Codex" and self.codex_plan:
            plan = PLAN_NAMES.get(self.codex_plan, self.codex_plan)
            self.plan_hint.setText(f"ChatGPT {plan}方案：Codex 只能使用 {FREE_CODEX_MODEL}。" if free
                                   else f"ChatGPT {plan}方案：可選擇各模型，括號內為特色說明。")
            self.plan_hint.show()
        else:
            self.plan_hint.hide()

    def set_codex_plan(self, plan):
        if plan == self.codex_plan:
            return
        if self.active_provider == "Codex":
            self.models["Codex"] = self.selected_model()
        self.codex_plan = plan
        if self.active_provider == "Codex":
            self.fill_models()

    def update_login_button(self):
        provider = self.provider.currentText()
        self.login_button.setText(
            f"已登入 {provider}" if self.login_states.get(provider) is True
            else f"登入 {provider} 帳號")

    def request_login_status(self, provider):
        self.login_checks[provider] += 1
        version = self.login_checks[provider]
        Thread(target=self.login_status_worker, args=(provider, version), daemon=True).start()

    def login_status_worker(self, provider, version):
        try:
            tool = find_tool(PROVIDER_TOOLS[provider])
            logged_in = cli_logged_in(provider, tool) if tool else None
        except Exception:
            logged_in = None
        self.events.put(("login_status", (provider, version, logged_in)))
        if provider == "Codex" and logged_in:
            # 只在本機讀取方案欄位；讀不到時維持完整模型清單。
            self.events.put(("codex_plan", codex_plan()))

    def browse_output(self):
        selected = QFileDialog.getExistingDirectory(self, '選擇本機輸出位置', self.output_dir.text())
        if selected:
            self.output_dir.setText(str(Path(selected)))
            self.remember_output()

    def reset_output(self):
        self.output_dir.setText(str(DEFAULT_OUTPUT))
        self.remember_output()

    def remember_output(self):
        """選定或修改本機輸出位置後立即保存，下次開啟沿用上次位置。"""
        value = self.output_dir.text().strip()
        if not value or not Path(value).expanduser().is_absolute():
            return
        settings = load_settings(self.settings_file)
        settings["output_dir"] = value
        try:
            save_settings(settings, self.settings_file)
        except OSError:
            pass

    def login_ai(self):
        """依目前選的 AI 平台，在背景開啟瀏覽器登入（Codex：ChatGPT 帳號；Claude：Pro／Max 帳號）。"""
        if self.busy:
            return
        provider = self.provider.currentText()
        tool = find_tool(PROVIDER_TOOLS[provider])
        if not tool:
            self.check_setup()
            return
        # 登入獨立於轉換工作：不鎖定主畫面、不進入自動修復或錯誤回報。
        self.login_cancel = Event()
        self.status.setText(f'正在開啟瀏覽器登入 {provider}，請完成帳號授權。')
        Thread(target=self.login_worker, args=(provider, tool, self.login_cancel), daemon=True).start()
        self.login_dialog = LoginWaitDialog(self, provider)
        # 以 accepted 訊號判斷，不比較 exec() 回傳值與列舉（PySide6 的列舉與 int 比較不一定相等）
        outcome = {"accepted": False}
        self.login_dialog.accepted.connect(lambda: outcome.update(accepted=True))
        self.login_dialog.exec()
        accepted = outcome["accepted"]
        self.login_dialog = None
        if not accepted:
            self.login_cancel.set()  # 結束背景的登入程式（codex login／claude auth login）
            self.status.setText(f'已取消 {provider} 登入，回到主畫面。')

    def close_login_dialog(self):
        if getattr(self, "login_dialog", None) is not None:
            self.login_dialog.accept()

    def check_setup(self):
        """主畫面內手動檢查 AI 桌面版；新裝好的平台會接著查詢登入狀態。"""
        if self.busy:
            return
        status = ai_tool_status()
        while show_setup_check(self, status) == "recheck":
            before, status = status, ai_tool_status()
            for provider, installed in status.items():
                if installed and not before.get(provider):
                    self.request_login_status(provider)

    def set_busy(self, busy):
        if busy and not self.busy:
            self.cancel_event = Event()
        self.stop_button.setEnabled(busy and not self.cancel_event.is_set())
        self.stop_button.setText("中止執行")
        self.busy = busy
        self.input_panel.setEnabled(not busy)
        self.start_button.setEnabled(not busy)
        self.start_button.setText('處理中…' if busy else '開始下載')
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setValue(0 if busy else 1)

    FORCE_STOP_DELAY_MS = 5000

    def stop(self):
        if not self.busy:
            return
        if self.cancel_event.is_set():
            # 已要求中止但仍在等候：第二次按下提供強制結束
            if ask_yes_no("強制結束", "目前步驟無法立即停止（例如正在下載語音模型或等候登入）。\n"
                          "要強制結束 RecipeLens 嗎？已產生的本機檔案會保留，未完成的步驟會中斷。",
                          parent=self, yes_text="強制結束", no_text="繼續等候"):
                self.force_quit()
            return
        self.cancel_event.set()
        kill_active_processes()  # 立即終止外部工具，不必等下一個檢查點
        self.pending_upload = None
        self.stop_button.setEnabled(False)
        self.stop_button.setText("正在中止…")
        self.status.setText("正在中止，等候目前工作安全停止；已產生的本機檔案會保留。")
        QTimer.singleShot(self.FORCE_STOP_DELAY_MS, self.offer_force_stop)

    def offer_force_stop(self):
        """中止後數秒仍未停止：把按鈕改為「強制結束」。"""
        if self.busy and self.cancel_event.is_set():
            self.stop_button.setEnabled(True)
            self.stop_button.setText("強制結束")
            self.status.setText("目前步驟無法立即停止。可繼續等候，或按右上角「強制結束」關閉 RecipeLens。")

    def force_quit(self):
        """終止外部工具並直接結束程式；用於中止後仍卡住、或處理中要關閉視窗。"""
        try:
            self.remember_url()
        except Exception:
            pass
        kill_active_processes()
        os._exit(0)

    def post_progress(self, text):
        check_cancelled()
        self.events.put(("progress", text))

    def pick_drive_folder(self):
        if not self.busy:
            self.connect('settings')

    def browse_drive(self, service):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        return choose_folder(self, service, (self.drive_folder or {}).get('id'))

    def open_output(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.parent)))

    def open_document(self, suffix):
        if self.result:
            target = self.result.with_suffix('.' + suffix)
            if target.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def display_result(self):
        self.result_path.setText(str(self.result))
        self.open_folder_button.setEnabled(True)
        for suffix, item in self.file_buttons.items():
            item.setEnabled(self.result.with_suffix('.' + suffix).is_file())
        try:
            self.preview.show_recipe(self.result)
            self.preview_stack.setCurrentIndex(1)
        except (OSError, ValueError) as error:
            self.log.appendPlainText(f'預覽無法載入，原始文件仍已保留：{error}')

    def update_progress(self, text):
        self.status.setText(text)
        self.log.appendPlainText(text)
        # 顯示實際階段，工作期間使用不定進度條，不捏造百分比。
        stage = None
        for index, words in enumerate((('下載', '取得影片', '讀取 YouTube'), ('字幕', '語音', '候選畫面'),
                                       ('Codex', 'Claude', '判讀', '整理'), ('PDF', 'DOCX', '匯出', '擷取步驟', '儲存'))):
            if any(word in text for word in words):
                stage = index
        if stage is not None:
            self.highlight_stage(stage)

    def highlight_stage(self, stage):
        for index, item in enumerate(self.phase_labels):
            item.setStyleSheet('color:#237fc6;font-weight:700;' if index == stage else 'color:#8293a6;')

    def remember_url(self):
        settings = load_settings(self.settings_file)
        settings["last_url"] = self.url.text().strip()
        try:
            save_settings(settings, self.settings_file)
        except OSError:
            pass

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
            if ask_yes_no('仍在處理', '要中止並關閉 RecipeLens 嗎？\n已產生的本機檔案會保留，未完成的步驟會中斷。',
                          parent=self, yes_text='中止並關閉', no_text='繼續處理'):
                self.cancel_event.set()
                self.force_quit()
        else:
            self.remember_url()
            self.timer.stop()
            event.accept()

    def login_worker(self, provider, tool, cancel=None):
        with cancel_scope(cancel):
            try:
                cli_login(provider, tool)
                self.events.put(("logged_in", provider))
            except JobCancelled:
                self.events.put(("login_cancelled", provider))
            except Exception as error:
                self.events.put(("login_failed", (provider, error_text(error))))

    def reset_recovery(self):
        self.repair_selected = False
        self.plan_blocked = False
        self.recovery_asked = False
        self.error_stage = "準備工作"
        self.recovery_notes = []
        self.job_provider = self.provider.currentText()
        self.job_model = self.selected_model() or None

    def current_settings(self):
        self.models[self.provider.currentText()] = self.selected_model()
        return {
            "last_url": self.url.text().strip(),
            "provider": self.provider.currentText(),
            "models": dict(self.models),
            "output_dir": self.output_dir.text().strip(),
            "auto_upload": self.upload_after.isChecked(),
            "local_formats": [suffix for suffix, item in self.local_formats.items() if item.isChecked()],
            "formats": [suffix for suffix, variable in self.cloud_formats.items() if variable.isChecked()],
            "drive_folder": self.drive_folder,
            "setup_done": load_settings(self.settings_file)["setup_done"],
        }

    def start(self):
        if self.busy:
            return
        url = self.url.text().strip()
        try:
            if detect_platform(url) != self.platform.currentText():
                raise ValueError("平台選項與網址不符，請重新確認。")
        except ValueError as error:
            show_error("請確認輸入", str(error), self)
            return
        try:
            file_stem = validate_filename(self.file_name.text()) if self.file_name.text().strip() else None
            formats = tuple(suffix for suffix, variable in self.cloud_formats.items() if variable.isChecked())
            if not self.output_dir.text().strip():
                raise ValueError("請在「本機設定」指定本機輸出位置。")
            output = Path(self.output_dir.text().strip()).expanduser()
            if not output.is_absolute():
                raise ValueError("本機輸出位置請填寫完整路徑，例如 C:\\Users\\User\\Documents\\食譜。")
            if output.exists() and not output.is_dir():
                raise ValueError("本機輸出位置不是資料夾，請重新選擇。")
            if self.upload_after.isChecked():
                if not self.drive_folder:
                    raise ValueError("已勾選「轉換完成後上傳到 Google Drive」，請先在「進階設定」按「選擇」"
                                     "指定雲端資料夾，或取消勾選只保留在本機。")
                if not formats:
                    raise ValueError("請在「進階設定」勾選至少一種上傳格式，或取消勾選上傳。")
        except ValueError as error:
            show_error("請確認設定", str(error), self)
            return
        options = dict(platform=self.platform.currentText(), subtitle_mode=self.subtitle_mode(),
                       keep_subtitles=self.keep.isChecked(),
                       speech_language=(self.speech_language.currentText()
                                        if self.subtitle_mode() == "none" else "其他"),
                       model=self.selected_model() or None, file_stem=file_stem,
                       provider=self.provider.currentText(), output=output,
                       local_formats=tuple(suffix for suffix, item in self.local_formats.items()
                                           if item.isChecked()))
        try:
            save_settings(self.current_settings(), self.settings_file)
        except OSError:
            pass  # 無法保存預設值不影響本次轉換
        # 設定在按下「開始下載」時定案：勾選上傳者轉換完成直接上傳到已選的資料夾。
        self.pending_upload = {"formats": formats} if self.upload_after.isChecked() else None
        self.reset_recovery()
        self.set_busy(True)
        self.log.clear()
        self.highlight_stage(0)
        self.status.setText("開始處理…")
        Thread(target=self.worker, args=(url, options), daemon=True).start()

    @cancellable_worker
    def worker(self, url, options):
        try:
            result = convert_video(url, progress=self.post_progress,
                                   on_error=self.recover, **options)
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", error_text(error)))

    def request_repair(self, error, stage):
        """背景執行緒等待主執行緒上的對話窗；widgets 只在 poll 操作。"""
        self.error_stage = stage
        self.recovery_asked = True
        answer = Future()
        self.events.put(("repair_question", (error_text(error), stage, answer)))
        while not answer.done():
            check_cancelled()
            self.cancel_event.wait(0.1)
        check_cancelled()
        return answer.result()

    def recover(self, error, stage):
        if isinstance(error, CodexPlanError):
            # Codex 版本過舊或帳號尚未開放：AI 修不了，也不是程式錯誤，不詢問修復、不回報開發者
            self.error_stage = stage
            self.recovery_asked = True
            self.plan_blocked = True
            return False
        if not self.request_repair(error, stage):
            self.repair_selected = False
            return False
        self.repair_selected = True
        try:
            self.events.put(("progress", f"正在檢查「{stage}」的錯誤原因…"))
            advice = diagnose(error, stage, self.job_provider, self.job_model)
            self.recovery_notes.append(advice["message"])
            self.events.put(("progress", advice["message"]))
            if advice["action"] == "login" and stage in {"AI 登入", "AI 判讀"}:
                tool = find_tool(PROVIDER_TOOLS[self.job_provider])
                if not tool:
                    raise ValueError("找不到 AI 登入工具。")
                cli_login(self.job_provider, tool)
                return True
            if advice["action"] == "retry":
                return True
            self.events.put(("repair_advice", advice["message"]))
        except Exception as diagnosis_error:
            message = f"自動診斷未完成，已中止本次工作：{error_text(diagnosis_error)}"
            self.recovery_notes.append(message)
            self.events.put(("repair_advice", message))
        return False

    def finish_error(self, message):
        if self.plan_blocked:
            self.pending_upload = None
            self.status.setText("Codex 拒絕所有模型，本次工作已中止，已完成的檔案會保留。")
            self.progress.setValue(0)
            self.log.appendPlainText(message)
            show_error("Codex 無法使用", message, self)
            return
        if not self.recovery_asked:
            self.recovery_asked = True
            if ask_yes_no("是否自動修復", f"{message}\n\n是否讓 AI 檢查錯誤原因？\n"
                          f"若無法修復，將中止工作並自動回報給 {REPORT_TARGET}。", parent=self):
                self.repair_selected = True
                self.set_busy(True)
                Thread(target=self.diagnose_terminal, args=(message,), daemon=True).start()
                return
        self.pending_upload = None
        self.status.setText("本次工作已中止，已完成的檔案會保留。")
        self.progress.setValue(0)
        self.log.appendPlainText(message)
        details = message
        if self.recovery_notes:
            details += "\n\n診斷結果：\n" + "\n".join(self.recovery_notes)
        body = report_body(details, self.job_provider, self.error_stage)
        if not self.repair_selected:
            show_error("處理已中止", details, self)
        if self.repair_selected or ask_yes_no(
                "是否回報錯誤", f"是否將以下錯誤摘要回報給 {REPORT_TARGET}？\n\n{body}", parent=self):
            self.set_busy(True)
            self.status.setText("本次工作已中止，正在送出錯誤報告…")
            Thread(target=self.report_worker, args=(body,), daemon=True).start()
        if self.repair_selected:
            show_error("自動修復未完成，工作已中止", details, self)

    @cancellable_worker
    def diagnose_terminal(self, message):
        """沒有可重試步驟的準備／收尾錯誤，診斷後中止，不重跑整支流程。"""
        try:
            advice = diagnose(message, self.error_stage, self.job_provider, self.job_model)
            self.recovery_notes.append(advice["message"])
            self.events.put(("repair_advice", advice["message"] + "\n此階段無法自動續跑，請依提示排除後重新開始。"))
        except Exception as error:
            self.recovery_notes.append("自動診斷失敗：" + error_text(error))
            self.events.put(("repair_advice", "自動診斷失敗：" + error_text(error)))
        self.events.put(("error", message))

    @cancellable_worker
    def report_worker(self, body):
        try:
            report_id = send_report(body)
            self.events.put(("report_sent", report_id))
        except Exception as error:
            # 回報失敗不進入修復迴圈，也不自動再次送出。
            self.events.put(("report_failed", error_text(error)))

    def select_all_formats(self):
        for variable in self.cloud_formats.values():
            variable.setChecked(True)

    def set_drive_folder(self, folder):
        """記住選定的雲端資料夾並保存為預設值。"""
        names = [part["name"] if isinstance(part, dict) else part for part in folder.get("path", [])]
        self.drive_folder = {"id": folder["id"], "name": folder["name"], "path": names or [folder["name"]]}
        self.drive_location.setText(format_location(self.drive_folder))
        try:
            save_settings(self.current_settings(), self.settings_file)
        except OSError:
            pass

    def after_conversion(self, source, formats):
        """轉換成功：上傳到按「開始下載」前選好的雲端資料夾，不再跳出詢問或資料夾視窗。"""
        source = Path(source)
        if not self.drive_folder or not formats:
            self.status.setText(f"轉換完成：{source.stem}。未設定雲端資料夾或上傳格式，資料只保留在本機：{source.parent}")
            return
        self.connect("upload", {"source": source, "formats": formats, "change": False})

    def connect(self, purpose, payload=None):
        if self.busy:
            return
        self.reset_recovery()
        self.set_busy(True)
        self.status.setText("正在連線 Google 雲端硬碟…首次使用或權限更新時，請在瀏覽器完成登入。")
        Thread(target=self.connect_worker, args=(purpose, payload), daemon=True).start()

    @cancellable_worker
    def connect_worker(self, purpose, payload=None):
        try:
            service = self.drive_service or perform("Google 連線", google_service, self.recover)
            self.events.put(("drive_ready", (purpose, payload, service)))
        except Exception as error:
            self.events.put(("error", f"無法連線 Google 雲端硬碟，本機檔案已保留。\n{error}"))

    def drive_ready(self, purpose, payload, service):
        self.drive_service = service
        if purpose == "settings":
            self.status.setText("請在視窗中選擇雲端存放位置。")
            folder = self.browse_drive(service)
            self.set_busy(False)
            if folder:
                self.set_drive_folder(folder)
                self.status.setText(f"雲端存放位置已設為：{self.drive_location.text()}")
            else:
                self.status.setText("未變更雲端存放位置。")
            return
        source, formats = payload["source"], payload["formats"]
        if payload["change"]:
            self.status.setText("請在視窗中選擇雲端存放位置。")
            folder = self.browse_drive(service)
            if folder is None:
                self.set_busy(False)
                self.status.setText("已取消上傳，本機 MD、PDF、DOCX 與圖片已保留。")
                return
            self.set_drive_folder(folder)
        folder = dict(self.drive_folder)
        # 每份食譜在根目錄下自動建立自己的資料夾；根目錄已由 set_drive_folder 記住。
        destination = {"file_stem": source.stem, "new_folder": source.stem}
        self.status.setText(f"正在上傳至 Google 雲端硬碟「{format_location(folder)} > {source.stem}」…")
        Thread(target=self.upload_worker,
               args=(source, formats, service, folder, destination), daemon=True).start()

    @cancellable_worker
    def upload_worker(self, source, formats, service, folder, destination):
        try:
            result = perform("雲端上傳", lambda: upload_recipe(
                source, formats, service=service, parent_id=folder["id"], **destination,
                progress=self.post_progress, stage_missing=True), self.recover)
            self.events.put(("uploaded", (result, folder)))
        except Exception as error:
            self.events.put(("error", f"雲端上傳失敗。本機 Markdown、圖片與已產生的文件均保留。\n{error}"))

    def show_upload_success(self, items, folder):
        recipe_folder = next((item for item in items if item.get("folder")), None)
        location = format_location(folder)
        if recipe_folder:
            location += " > " + recipe_folder["name"].split("／")[0]
        self.status.setText(f"上傳成功！已上傳至「{location}」，本機原檔與轉檔均已保留。")
        names = "\n".join(f"• {item['name']}" for item in items if not item.get("folder"))
        if ask_yes_no("上傳成功",
                               f"已上傳到 Google 雲端硬碟：\n{location}\n\n{names}\n\n要在瀏覽器開啟這個資料夾嗎？",
                               parent=self):
            webbrowser.open(recipe_folder["url"] if recipe_folder
                            else f"https://drive.google.com/drive/folders/{folder['id']}")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "login_status":
                    provider, version, logged_in = value
                    if version == self.login_checks[provider]:
                        self.login_states[provider] = logged_in
                        self.update_login_button()
                    continue
                if kind == "logged_in":
                    self.close_login_dialog()
                    self.login_checks[value] += 1
                    self.login_states[value] = True
                    self.update_login_button()
                    self.status.setText(f"{value} 已登入，可以開始下載。")
                    if value == "Codex":
                        self.set_codex_plan(codex_plan())
                    continue
                if kind == "login_failed":
                    provider, message = value
                    if getattr(self, "login_cancel", None) is not None and self.login_cancel.is_set():
                        continue  # 使用者已取消，不再顯示錯誤
                    self.close_login_dialog()
                    self.status.setText(f"{provider} 登入未完成，可再按一次登入。")
                    show_error("登入未完成", message, self)
                    continue
                if kind == "login_cancelled":
                    continue
                if kind == "codex_plan":
                    if not self.busy:
                        self.set_codex_plan(value)
                    continue
                if self.cancel_event.is_set():
                    if kind == "repair_question":
                        value[2].set_result(False)
                        continue
                    if kind in {"progress", "repair_advice"}:
                        continue
                    self.set_busy(False)
                    self.pending_upload = None
                    self.progress.setValue(0)
                    self.status.setText("本次工作已中止，已產生的本機檔案均保留。")
                    continue
                if kind == "progress":
                    self.update_progress(value)
                elif kind == "repair_question":
                    message, stage, answer = value
                    try:
                        answer.set_result(ask_yes_no(
                            "是否自動修復", f"「{stage}」發生錯誤：\n{message}\n\n是否自動修復？\n"
                            "同意後可能使用所選 AI 的額度診斷，僅重試失敗步驟一次。\n"
                            f"若仍失敗，將中止本次工作並自動回報去識別錯誤摘要給 {REPORT_TARGET}。",
                            parent=self, yes_text="是，自動修復", no_text="否，中止工作"))
                    except Exception:
                        answer.set_result(False)
                elif kind == "repair_advice":
                    self.log.appendPlainText(value)
                    self.status.setText(value)
                elif kind == "drive_ready":
                    self.drive_ready(*value)
                else:
                    self.set_busy(False)
                    if kind == "done":
                        self.result = Path(value).resolve()
                        self.display_result()
                        self.highlight_stage(3)
                        self.status.setText(f"轉換完成：{self.result.stem}，本機檔案位於 {self.result.parent}")
                        if self.pending_upload:
                            settings = self.pending_upload
                            self.pending_upload = None
                            self.after_conversion(value, **settings)
                    elif kind == "uploaded":
                        self.show_upload_success(*value)
                    elif kind == "report_sent":
                        self.status.setText(f"本次工作已中止，錯誤報告已送給 {REPORT_TARGET}，回報編號：{value}")
                    elif kind == "report_failed":
                        self.status.setText("本次工作已中止，錯誤報告送出失敗。")
                        self.log.appendPlainText(value)
                        show_error("錯誤報告未送出", value, self)
                    else:
                        self.finish_error(value)
        except Empty:
            pass

def setup_gate(settings_file=SETTINGS_FILE, status_source=ai_tool_status):
    """啟動檢查：首次啟動一律先顯示環境檢查；之後只在兩種 AI 桌面版都找不到時顯示。

    至少找到一種才回傳 True 進入主畫面；使用者選「離開」回傳 False。
    """
    settings = load_settings(settings_file)
    status = status_source()
    if settings["setup_done"] and any_installed(status):
        return True
    while True:
        action = show_setup_check(None, status, gate=True)
        if action == "recheck":
            status = status_source()
            continue
        if action == "enter" and any_installed(status):
            break
        return False
    settings = load_settings(settings_file)
    settings["setup_done"] = True
    try:
        save_settings(settings, settings_file)
    except OSError:
        pass
    return True


def main():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RecipeLens.App')
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('RecipeLens')
    apply_style(app)
    if not setup_gate():
        return 0
    window = RecipeLensApp()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

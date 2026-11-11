"""PySide6 介面元件；背景工作由主視窗控制器協調。"""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QTextDocument
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSplitter, QStackedWidget,
    QTextBrowser, QVBoxLayout, QWidget)
from .ai_recipe import AI_PROVIDERS
from .settings import UPLOAD_FORMATS
from .media import SPEECH_LANGUAGES
from .setup_check import INSTALL_GUIDES, any_installed, setup_summary

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "icons"


def label(text, name=None, wrap=False):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(wrap)
    return item


def button(text, slot, name=None):
    item = QPushButton(text)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        item.setObjectName(name)
    item.clicked.connect(slot)
    return item


def row(*widgets):
    layout = QHBoxLayout()
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def card(title, caption=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(8)
    layout.addWidget(label(title, "cardTitle"))
    if caption:
        layout.addWidget(label(caption, "muted", True))
    return frame, layout


def format_location(folder):
    return " > ".join(folder.get("path") or [folder["name"]]) if folder else "尚未選擇雲端資料夾"


def show_error(title, text, parent=None):
    QMessageBox.critical(parent, title, text)


def show_info(title, text, parent=None):
    QMessageBox.information(parent, title, text)


def ask_yes_no(title, text, parent=None, *, yes_text="是", no_text="否"):
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    yes = box.addButton(yes_text, QMessageBox.ButtonRole.YesRole)
    box.addButton(no_text, QMessageBox.ButtonRole.NoRole)
    box.exec()
    return box.clickedButton() == yes


class RecipePreview(QTextBrowser):
    """限制圖片來源至本次食譜資料夾，禁止遠端圖片請求。"""
    def __init__(self):
        super().__init__()
        self.recipe_dir = None
        self.setOpenLinks(False)
        self.anchorClicked.connect(self.open_link)
        self.document().setDefaultStyleSheet(
            "h1 {color:#18395e;font-size:25px;} h2 {color:#2777b8;font-size:19px;} "
            "p,li {line-height:155%;} td,th {padding:7px;border:1px solid #dce6f0;}")

    def loadResource(self, resource_type, url):
        if resource_type != QTextDocument.ResourceType.ImageResource or not self.recipe_dir:
            return None
        resolved = self.document().baseUrl().resolved(url)
        if not resolved.isLocalFile():
            return None
        path = Path(resolved.toLocalFile()).resolve()
        if not path.is_relative_to(self.recipe_dir):
            return None
        image = QPixmap(str(path))
        if image.isNull():
            return None
        return image.scaledToWidth(440, Qt.TransformationMode.SmoothTransformation) if image.width() > 440 else image

    def show_recipe(self, source):
        source = Path(source).resolve()
        text = source.read_text(encoding="utf-8")
        self.recipe_dir = source.parent
        self.document().setBaseUrl(QUrl.fromLocalFile(str(source.parent) + "/"))
        self.setMarkdown(text)

    def open_link(self, url):
        if url.scheme() in {"https", "http"}:
            QDesktopServices.openUrl(url)


class WindowUi:
    def build_ui(self, settings):
        base = QWidget()
        self.setCentralWidget(base)
        page = QVBoxLayout(base)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        header = QWidget()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(28, 16, 28, 16)
        icon = QLabel()
        icon.setPixmap(QPixmap(str(ASSETS / "recipelens_256.png")).scaled(
            QSize(46, 46), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        head.addWidget(icon)
        title = QVBoxLayout()
        title.setSpacing(1)
        title.addWidget(label("RecipeLens", "brand"))
        title.addWidget(label("把喜歡的料理影片，收藏成自己的食譜。", "subtitle"))
        head.addLayout(title)
        head.addStretch()
        self.stop_button = button("中止執行", self.stop)
        self.stop_button.setEnabled(False)
        head.addWidget(self.stop_button)
        page.addWidget(header)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(18)
        split.setChildrenCollapsible(False)
        page.addWidget(split, 1)
        scroll = QScrollArea()
        self.input_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
        self.input_panel = QWidget()
        inputs = QVBoxLayout(self.input_panel)
        inputs.setContentsMargins(26, 20, 2, 20)
        inputs.setSpacing(12)
        inputs.addWidget(label("開始一份新食譜", "heading"))
        inputs.addWidget(label("貼上公開影片網址，剩下的交給 RecipeLens。", "muted", True))
        source, layout = card("01　影片來源")
        self.url = QLineEdit()
        self.url.setPlaceholderText("YouTube 或 Facebook 影片網址")
        self.url.setClearButtonEnabled(True)
        self.url.textChanged.connect(self.detect)
        layout.addLayout(row(self.url, button("貼上", self.paste)))
        self.platform = QComboBox()
        self.platform.addItems(["Facebook", "YouTube"])
        layout.addLayout(row(label("影片平台"), self.platform))
        layout.addWidget(label("依網址自動判讀，你也可以手動確認。", "muted", True))
        inputs.addWidget(source)
        ai, layout = card("02　AI 模型選定")
        self.provider = QComboBox()
        self.provider.addItems(list(AI_PROVIDERS))
        self.provider.setCurrentText(settings["provider"])
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumContentsLength(18)
        self.provider.currentTextChanged.connect(self.change_provider)
        layout.addLayout(row(self.provider, self.model))
        self.plan_hint = label("", "muted", True)
        self.plan_hint.hide()
        layout.addWidget(self.plan_hint)
        self.login_button = button(f"登入 {settings['provider']} 帳號", self.login_ai)
        layout.addWidget(self.login_button)
        layout.addWidget(button("檢查 AI 桌面版安裝", lambda: self.check_setup(), "link"))
        inputs.addWidget(ai)
        output, layout = card("03　本機設定")
        self.output_dir = QLineEdit(settings["output_dir"])
        layout.addWidget(label("本機輸出位置"))
        layout.addLayout(row(self.output_dir, button("瀏覽", self.browse_output)))
        layout.addWidget(button("還原預設位置", self.reset_output, "link"))
        layout.addWidget(label("食譜命名"))
        self.file_name = QLineEdit()
        self.file_name.setPlaceholderText("留空依平台、頻道與食譜名稱命名")
        layout.addWidget(self.file_name)
        layout.addWidget(label("檔案輸出類型"))
        self.local_formats = {}
        for suffix, title in zip(UPLOAD_FORMATS, ("MD、images 資料夾與截圖（必選）", "PDF", "DOCX")):
            item = QCheckBox(title)
            item.setChecked(suffix in settings["local_formats"])
            self.local_formats[suffix] = item
        self.local_formats["md"].setEnabled(False)
        layout.addWidget(self.local_formats["md"])
        layout.addLayout(row(self.local_formats["pdf"], self.local_formats["docx"]))
        inputs.addWidget(output)
        self.more_button = button("進階設定　＋", self.toggle_advanced, "link")
        inputs.addWidget(self.more_button)
        self.advanced = QWidget()
        self.build_advanced(self.advanced, settings)
        inputs.addWidget(self.advanced)
        self.advanced.hide()
        inputs.addStretch()
        scroll.setWidget(self.input_panel)
        split.addWidget(scroll)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 24, 26, 24)
        right_layout.setSpacing(16)
        progress, layout = card("處理進度")
        self.phase_labels = []
        steps = QHBoxLayout()
        for text in ("1  下載", "2  辨識", "3  整理", "4  產生文件"):
            stage = label(text, "muted")
            self.phase_labels.append(stage)
            steps.addWidget(stage)
        layout.addLayout(steps)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = label("準備就緒，貼上影片網址後即可開始。", "muted", True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        layout.addWidget(button("查看處理紀錄", self.toggle_log, "link"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        self.log.setMaximumHeight(110)
        self.log.hide()
        layout.addWidget(self.log)
        right_layout.addWidget(progress)
        preview_card, layout = card("食譜預覽")
        self.preview_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        symbol = label("▤", "heading")
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        symbol.setStyleSheet("font-size:54px;color:#8cb7df;")
        empty_layout.addWidget(symbol)
        title = label("下一道拿手菜，從這裡開始", "cardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(title)
        note = label("完成後顯示食材、做法與步驟截圖。\n所有文件都會保存在你的電腦。", "muted", True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(note)
        self.preview_stack.addWidget(empty)
        self.preview = RecipePreview()
        self.preview_stack.addWidget(self.preview)
        layout.addWidget(self.preview_stack, 1)
        self.result_path = QLineEdit()
        self.result_path.setReadOnly(True)
        self.result_path.setPlaceholderText("完成後顯示本機檔案路徑")
        layout.addWidget(self.result_path)
        self.open_folder_button = button("開啟資料夾", self.open_output)
        self.open_folder_button.setEnabled(False)
        self.file_buttons = {}
        actions = QHBoxLayout()
        actions.addWidget(self.open_folder_button)
        actions.addStretch()
        for suffix in UPLOAD_FORMATS:
            item = button(suffix.upper(), lambda checked=False, fmt=suffix: self.open_document(fmt))
            item.setEnabled(False)
            self.file_buttons[suffix] = item
            actions.addWidget(item)
        layout.addLayout(actions)
        right_layout.addWidget(preview_card, 1)
        split.addWidget(right)
        split.setSizes([490, 710])
        footer = QWidget()
        footer.setObjectName("header")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(28, 14, 28, 14)
        foot.addStretch()
        self.start_button = button("開始下載", self.start, "primary")
        self.start_button.setMinimumWidth(210)
        foot.addWidget(self.start_button)
        foot.addStretch()
        page.addWidget(footer)

    def build_advanced(self, box, settings):
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        subtitles, layout = card("04　字幕與語音")
        self.subtitle_group = QButtonGroup(self)
        self.subtitle_buttons = {}
        for mode, text in [("original", "自動尋找平台字幕"), ("embedded", "沒有字幕檔，畫面內有字幕"),
                           ("none", "沒有字幕檔，畫面內也沒有字幕")]:
            option = QRadioButton(text)
            self.subtitle_group.addButton(option)
            self.subtitle_buttons[mode] = option
            layout.addWidget(option)
        self.subtitle_buttons["original"].setChecked(True)
        self.subtitle_group.buttonClicked.connect(self.update_subtitles)
        layout.addWidget(label("找不到平台字幕時，自動改用本機語音辨識。", "muted", True))
        self.speech_row = QWidget()
        speech = QHBoxLayout(self.speech_row)
        speech.setContentsMargins(0, 0, 0, 0)
        self.speech_language = QComboBox()
        self.speech_language.addItems(SPEECH_LANGUAGES)
        self.speech_language.setCurrentText("國語")
        self.speech_language.currentTextChanged.connect(self.update_speech_note)
        speech.addWidget(label("影片語音"))
        speech.addWidget(self.speech_language, 1)
        layout.addWidget(self.speech_row)
        self.speech_note = label("", "muted", True)
        layout.addWidget(self.speech_note)
        self.keep = QCheckBox("在食譜末尾保留完整字幕文字")
        layout.addWidget(self.keep)
        box.layout().addWidget(subtitles)
        cloud, layout = card("05　Google 雲端上傳")
        self.upload_after = QCheckBox("轉換完成後上傳到 Google Drive")
        self.upload_after.setChecked(settings["auto_upload"])
        layout.addWidget(self.upload_after)
        layout.addWidget(label("勾選時請先在下方選好雲端資料夾；按「開始下載」後轉換與上傳一次完成，"
                               "中途不再詢問。取消勾選則只保留在本機。", "muted", True))
        layout.addWidget(label("雲端硬碟位置"))
        self.drive_location = QLineEdit(format_location(self.drive_folder))
        self.drive_location.setReadOnly(True)
        self.drive_button = button("選擇", self.pick_drive_folder)
        layout.addLayout(row(self.drive_location, self.drive_button))
        layout.addWidget(label("選擇資料夾只會記住位置，不會開始處理；每份食譜在其中建立獨立資料夾。", "muted", True))
        layout.addWidget(label("雲端上傳類型"))
        formats = QHBoxLayout()
        self.cloud_formats = {}
        for suffix in UPLOAD_FORMATS:
            item = QCheckBox(suffix.upper())
            item.setChecked(suffix in settings["formats"])
            self.cloud_formats[suffix] = item
            formats.addWidget(item)
        formats.addWidget(button("全部選取", self.select_all_formats, "link"))
        layout.addLayout(formats)
        layout.addWidget(label("MD 上傳包含 images 資料夾與截圖。", "muted", True))
        box.layout().addWidget(cloud)


class LoginWaitDialog(QDialog):
    """等待瀏覽器登入。按「取消登入」或關閉視窗即回到主畫面，並結束背景的登入程式。"""

    def __init__(self, parent, provider):
        super().__init__(parent)
        account = "ChatGPT 帳號" if provider == "Codex" else "Claude Pro／Max 帳號"
        site = "ChatGPT" if provider == "Codex" else "Claude"
        self.setWindowTitle(f"登入 {provider}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("請在瀏覽器完成登入", "heading"))
        layout.addWidget(label(f"已開啟瀏覽器，請用{account}登入並按「允許」，完成後這個視窗會自動關閉。", wrap=True))
        layout.addWidget(label(f"想換帳號：先在瀏覽器的 {site} 網站登出，或按「取消登入」後再重新登入。\n"
                               "關閉瀏覽器分頁不會通知 RecipeLens；要放棄登入請按「取消登入」。", "muted", True))
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("取消登入", self.reject))
        layout.addLayout(buttons)


def show_setup_check(parent, status, gate=False):
    """AI 環境檢查畫面。

    gate=True 為啟動檢查：按鈕為「離開」「重新檢查」「進入主畫面」，至少裝好一種才能進入。
    回傳 "enter"、"recheck"、"quit"（啟動檢查）或 "close"（主畫面內手動檢查）。
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("RecipeLens · 環境檢查")
    if parent is None:
        dialog.setWindowIcon(QIcon(str(ASSETS / "recipelens.ico")))
    dialog.setMinimumWidth(600)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(14)
    layout.addWidget(label("開始前，先確認 AI 桌面版", "heading"))
    layout.addWidget(label(setup_summary(status), wrap=True))
    for provider, guide in INSTALL_GUIDES.items():
        installed = status.get(provider)
        frame, box = card(f"{guide.name}　{'✅ 已安裝' if installed else '⚠️ 未安裝'}")
        box.addWidget(label(guide.plan, "muted", True))
        if not installed:
            box.addWidget(label(guide.steps, wrap=True))
            link = QLabel(f'<a href="{guide.url}">{guide.url}</a>')
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            link.setOpenExternalLinks(True)
            box.addWidget(link)
            command = QLineEdit(guide.command)
            command.setReadOnly(True)
            command.setCursorPosition(0)
            command.setToolTip("也可複製這行貼到 PowerShell 安裝")
            copy = button("複製指令", lambda _=False, text=guide.command: QApplication.clipboard().setText(text))
            open_page = button("開啟下載頁", lambda _=False, url=guide.url: QDesktopServices.openUrl(QUrl(url)), "primary")
            box.addLayout(row(command, copy, open_page))
        layout.addWidget(frame)
    if not all(status.get(p) for p in INSTALL_GUIDES):
        layout.addWidget(label("已安裝卻仍顯示未安裝：請確認已依上方步驟開啟桌面版並登入一次，再按「重新檢查」。", "muted", True))
    choice = {"value": "quit" if gate else "close"}

    def finish(value):
        choice["value"] = value
        dialog.accept()

    buttons = QHBoxLayout()
    if gate:
        buttons.addWidget(button("離開", lambda: finish("quit")))
    buttons.addStretch()
    if not gate:
        buttons.addWidget(button("關閉", lambda: finish("close")))
    recheck = button("重新檢查", lambda: finish("recheck"))
    buttons.addWidget(recheck)
    if gate:
        enter = button("進入主畫面", lambda: finish("enter"), "primary")
        enter.setEnabled(any_installed(status))
        enter.setDefault(any_installed(status))
        buttons.addWidget(enter)
    recheck.setDefault(not gate or not any_installed(status))
    layout.addLayout(buttons)
    dialog.exec()
    return choice["value"]

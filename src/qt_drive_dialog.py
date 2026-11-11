"""Qt 雲端資料夾選擇器。API 呼叫在背景執行，空資料夾也能選取。"""
from queue import Empty, Queue
from threading import Thread
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLineEdit,
    QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from . import drive_browser as api
from .qt_window import button, label, show_error


class DriveFolderDialog(QDialog):
    def __init__(self, parent, service, start_folder=None):
        super().__init__(parent)
        self.service = service
        self.selection = None
        self.path = []
        self.loading = False
        self.events = Queue()
        self.setWindowTitle("選擇 Google Drive 存放位置")
        self.resize(700, 520)
        self.setMinimumSize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("選擇雲端資料夾", "heading"))
        layout.addWidget(label("雙擊進入資料夾；也可以直接使用目前位置。", "muted", True))
        toolbar = QHBoxLayout()
        self.up_button = button("上一層", self.go_up)
        self.new_button = button("新增資料夾", self.new_folder)
        self.refresh_button = button("重新整理", self.refresh)
        icons = ((self.up_button, QStyle.StandardPixmap.SP_FileDialogToParent, "回上一層資料夾"),
                 (self.new_button, QStyle.StandardPixmap.SP_FileDialogNewFolder, "在目前位置新增資料夾"),
                 (self.refresh_button, QStyle.StandardPixmap.SP_BrowserReload, "重新讀取資料夾"))
        for item, icon, tip in icons:
            item.setIcon(self.style().standardIcon(icon))
            item.setToolTip(tip)
            toolbar.addWidget(item)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.location = QLineEdit()
        self.location.setReadOnly(True)
        layout.addWidget(self.location)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["資料夾名稱", "修改時間"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 400)
        self.tree.itemDoubleClicked.connect(self.open_selected)
        self.tree.itemSelectionChanged.connect(self.update_target)
        layout.addWidget(self.tree, 1)
        self.target = label("正在讀取資料夾…", "muted", True)
        layout.addWidget(self.target)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("取消", self.reject))
        self.choose_button = button("使用此資料夾", self.choose, "primary")
        buttons.addWidget(self.choose_button)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(80)
        self.start(start_folder)

    def set_loading(self, loading):
        self.loading = loading
        self.tree.setEnabled(not loading)
        self.up_button.setEnabled(not loading and len(self.path) > 1)
        self.new_button.setEnabled(not loading and bool(self.path))
        self.refresh_button.setEnabled(not loading)
        self.choose_button.setEnabled(not loading and bool(self.path))
        if loading:
            self.target.setText("正在連線 Google Drive…")

    def run_task(self, work, success):
        if self.loading:
            return
        self.set_loading(True)
        events = self.events

        def worker():
            try:
                events.put((success, work(), None))
            except Exception as error:
                events.put((success, None, str(error)))
        Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                success, value, error = self.events.get_nowait()
                self.set_loading(False)
                if error:
                    self.target.setText("無法完成操作，可重新整理或取消。")
                    show_error("Google Drive 操作失敗", error, self)
                else:
                    success(value)
        except Empty:
            pass

    def start(self, start_folder):
        def load():
            try:
                if not start_folder:
                    raise ValueError
                path = api.folder_path(self.service, start_folder)
            except Exception:
                root = api.get_folder(self.service, "root")
                path = [{"id": root["id"], "name": "我的雲端硬碟"}]
            return path, api.list_child_folders(self.service, path[-1]["id"])
        self.run_task(load, self.show_folders)

    def show_folders(self, value, selected_id=None):
        self.path, folders = value
        self.tree.clear()
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        for folder in folders:
            item = QTreeWidgetItem([folder["name"], (folder.get("modifiedTime") or "")[:16].replace("T", " ")])
            item.setData(0, Qt.ItemDataRole.UserRole, folder)
            item.setIcon(0, icon)
            self.tree.addTopLevelItem(item)
            if folder["id"] == selected_id:
                self.tree.setCurrentItem(item)
        self.location.setText(" > ".join(part["name"] for part in self.path))
        self.set_loading(False)
        self.update_target()

    def refresh(self):
        if self.path:
            path = list(self.path)
            self.run_task(lambda: (path, api.list_child_folders(self.service, path[-1]["id"])), self.show_folders)
        else:
            self.start(None)

    def enter(self, folder):
        path = [*self.path, {"id": folder["id"], "name": folder["name"]}]
        self.run_task(lambda: (path, api.list_child_folders(self.service, folder["id"])), self.show_folders)

    def open_selected(self, *_):
        if not self.loading and self.tree.currentItem():
            self.enter(self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole))

    def go_up(self):
        if len(self.path) > 1:
            path = self.path[:-1]
            self.run_task(lambda: (path, api.list_child_folders(self.service, path[-1]["id"])), self.show_folders)

    def selected_target(self):
        if not self.path:
            return None
        item = self.tree.currentItem()
        if item:
            folder = item.data(0, Qt.ItemDataRole.UserRole)
            return {"id": folder["id"], "name": folder["name"],
                    "path": [*self.path, {"id": folder["id"], "name": folder["name"]}]}
        return {**self.path[-1], "path": list(self.path)}

    def update_target(self):
        target = self.selected_target()
        if target and not self.loading:
            self.target.setText("存放位置：" + " > ".join(part["name"] for part in target["path"]))

    def new_folder(self):
        if self.loading or not self.path:
            return
        name, ok = QInputDialog.getText(self, "新增資料夾", "資料夾名稱", text="新資料夾")
        if not ok:
            return
        path = list(self.path)

        def create():
            created = api.create_folder(self.service, path[-1]["id"], name)
            return (path, api.list_child_folders(self.service, path[-1]["id"])), created["id"]
        self.run_task(create, lambda value: self.show_folders(value[0], value[1]))

    def choose(self):
        if self.loading:
            return
        target = self.selected_target()
        if not target:
            return

        def verify():
            folder = api.get_folder(self.service, target["id"])
            if folder.get("trashed") or folder.get("mimeType") != api.FOLDER_MIME:
                raise ValueError("這個資料夾已不存在，請重新選擇。")
            if not folder.get("capabilities", {}).get("canAddChildren", True):
                raise ValueError("沒有在這個資料夾新增檔案的權限。")
            try:
                api.write_json(api.LAST_FOLDER_FILE, {"id": target["id"], "name": target["name"],
                    "url": f"https://drive.google.com/drive/folders/{target['id']}"})
            except OSError:
                pass
            return target

        def accept(target):
            self.selection = target
            self.timer.stop()
            self.accept()
        self.run_task(verify, accept)

    def reject(self):
        self.timer.stop()
        super().reject()

    def show_selection(self):
        self.exec()
        self.timer.stop()
        return self.selection

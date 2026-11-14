"""雲端資料夾瀏覽視窗：在 App 根資料夾內列出、進入、上一層、新增與選定，Drive API 以模擬物件代替。"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src import drive_browser
from tests.qt_support import QT_APP

FOLDER = drive_browser.FOLDER_MIME
APP_ROOT = {"id": "app-root", "name": "食影筆記"}


class FakeDrive:
    """以 dict 模擬 drive.file 看得到的資料夾樹：只有 App 根資料夾及其內容，看不到「我的雲端硬碟」。"""
    def __init__(self):
        self.items = {
            "app-root": {"id": "app-root", "name": "食影筆記", "mimeType": FOLDER, "parents": ["my-drive"]},
            "a": {"id": "a", "name": "09.我的食譜", "mimeType": FOLDER, "parents": ["app-root"]},
            "b": {"id": "b", "name": "工作", "mimeType": FOLDER, "parents": ["app-root"]},
            "c": {"id": "c", "name": "湯品", "mimeType": FOLDER, "parents": ["a"]},
            # App 建立後被使用者移到根資料夾外的資料夾，上層無權存取。
            "outside": {"id": "outside", "name": "外面", "mimeType": FOLDER, "parents": ["my-drive"]},
        }
        self.created = 0

    def get(self, folder_id):
        if folder_id not in self.items:
            raise LookupError("File not found")
        item = dict(self.items[folder_id])
        item["capabilities"] = {"canAddChildren": True}
        return item

    def children(self, parent):
        return [dict(v, modifiedTime="2026-11-09T10:00:00Z") for v in self.items.values()
                if parent in v["parents"]]

    def create(self, parent, name):
        self.created += 1
        item = {"id": f"new{self.created}", "name": name, "mimeType": FOLDER, "parents": [parent]}
        self.items[item["id"]] = item
        return item


class DriveBrowserTests(unittest.TestCase):
    def setUp(self):
        self.qt = QT_APP
        self.dialogs = []
        self.drive = FakeDrive()
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(drive_browser, "get_folder", lambda s, i: self.drive.get(i)),
            patch.object(drive_browser, "list_child_folders", lambda s, p: self.drive.children(p)),
            patch.object(drive_browser, "create_folder", lambda s, p, n: self.drive.create(p, n)),
            patch.object(drive_browser, "app_root_folder", lambda s: dict(APP_ROOT)),
            patch.object(drive_browser, "LAST_FOLDER_FILE", Path(self.tmp.name) / "last.json"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        for dialog in self.dialogs:
            dialog.reject()
            dialog.deleteLater()
        self.qt.processEvents()
        self.tmp.cleanup()

    def wait(self, dialog):
        deadline = time.monotonic() + 3
        while dialog.loading and time.monotonic() < deadline:
            dialog.poll()
            self.qt.processEvents()
            time.sleep(0.005)
        self.assertFalse(dialog.loading, '資料夾背景工作逾時')

    def open_dialog(self, start_folder=None):
        dialog = drive_browser.DriveFolderDialog(None, object(), start_folder)
        self.dialogs.append(dialog)
        self.wait(dialog)
        return dialog

    def names(self, dialog):
        return [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]

    def select(self, dialog, name):
        for i in range(dialog.tree.topLevelItemCount()):
            item = dialog.tree.topLevelItem(i)
            if item.text(0) == name:
                dialog.tree.setCurrentItem(item)
                return

    def test_navigate_up_and_down(self):
        dialog = self.open_dialog()
        self.assertEqual(sorted(self.names(dialog)), ["09.我的食譜", "工作"])
        self.assertFalse(dialog.up_button.icon().isNull())
        self.assertFalse(dialog.new_button.icon().isNull())
        self.assertFalse(dialog.up_button.isEnabled())
        self.select(dialog, "09.我的食譜")
        dialog.open_selected()
        self.wait(dialog)
        self.assertEqual(self.names(dialog), ["湯品"])
        self.assertEqual(dialog.location.text(), "食影筆記 > 09.我的食譜")
        dialog.go_up()
        self.wait(dialog)
        self.assertEqual(dialog.location.text(), "食影筆記")
        self.assertFalse(dialog.up_button.isEnabled())  # 不能離開 App 根資料夾
        dialog.reject()

    def test_start_in_last_folder(self):
        dialog = self.open_dialog(start_folder="c")
        self.assertEqual(dialog.location.text(), "食影筆記 > 09.我的食譜 > 湯品")
        dialog.reject()

    def test_new_folder_is_created_and_selected(self):
        dialog = self.open_dialog(start_folder="a")
        with patch("src.qt_drive_dialog.QInputDialog.getText", return_value=("甜點", True)):
            dialog.new_folder()
            self.wait(dialog)
        self.assertIn("甜點", self.names(dialog))
        self.assertEqual(dialog.selected_target()["name"], "甜點")
        self.assertEqual(self.drive.items["new1"]["parents"], ["a"])
        dialog.reject()

    def test_choose_selected_or_current_folder(self):
        dialog = self.open_dialog(start_folder="a")
        dialog.choose()
        self.wait(dialog)
        self.assertEqual(dialog.selection["id"], "a")
        self.assertEqual(drive_browser.last_folder_id(), "a")
        dialog = self.open_dialog(start_folder="a")
        self.select(dialog, "湯品")
        dialog.choose()
        self.wait(dialog)
        self.assertEqual(dialog.selection["id"], "c")
        self.assertEqual([p["name"] for p in dialog.selection["path"]], ["食影筆記", "09.我的食譜", "湯品"])

    def test_cancel_returns_none(self):
        dialog = self.open_dialog()
        dialog.reject()
        self.assertIsNone(dialog.selection)

    def test_missing_last_folder_falls_back_to_root(self):
        dialog = self.open_dialog(start_folder="gone")
        self.assertEqual(dialog.location.text(), "食影筆記")
        dialog.reject()

    def test_folder_outside_app_root_falls_back_to_root(self):
        dialog = self.open_dialog(start_folder="outside")
        self.assertEqual(dialog.location.text(), "食影筆記")
        self.assertEqual(sorted(self.names(dialog)), ["09.我的食譜", "工作"])
        dialog.reject()


if __name__ == "__main__":
    unittest.main(verbosity=2)

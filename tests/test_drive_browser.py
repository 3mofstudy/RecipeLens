"""雲端資料夾瀏覽視窗：列出、進入、上一層、新增資料夾與選定，Drive API 以模擬物件代替。"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src import drive_browser
from tests.qt_support import QT_APP

FOLDER = drive_browser.FOLDER_MIME


class FakeDrive:
    """以 dict 模擬 Drive 資料夾樹。"""
    def __init__(self):
        self.items = {
            "root-id": {"id": "root-id", "name": "My Drive", "mimeType": FOLDER, "parents": []},
            "a": {"id": "a", "name": "09.我的食譜", "mimeType": FOLDER, "parents": ["root-id"]},
            "b": {"id": "b", "name": "工作", "mimeType": FOLDER, "parents": ["root-id"]},
            "c": {"id": "c", "name": "湯品", "mimeType": FOLDER, "parents": ["a"]},
        }
        self.created = 0

    def get(self, folder_id):
        item = dict(self.items["root-id" if folder_id == "root" else folder_id])
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
        self.assertEqual(dialog.location.text(), "我的雲端硬碟 > 09.我的食譜")
        dialog.go_up()
        self.wait(dialog)
        self.assertEqual(dialog.location.text(), "我的雲端硬碟")
        dialog.reject()

    def test_start_in_last_folder(self):
        dialog = self.open_dialog(start_folder="c")
        self.assertEqual(dialog.location.text(), "我的雲端硬碟 > 09.我的食譜 > 湯品")
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
        self.assertEqual([p["name"] for p in dialog.selection["path"]], ["我的雲端硬碟", "09.我的食譜", "湯品"])

    def test_cancel_returns_none(self):
        dialog = self.open_dialog()
        dialog.reject()
        self.assertIsNone(dialog.selection)

    def test_missing_last_folder_falls_back_to_root(self):
        dialog = self.open_dialog(start_folder="gone")
        self.assertEqual(dialog.location.text(), "我的雲端硬碟")
        dialog.reject()


if __name__ == "__main__":
    unittest.main(verbosity=2)

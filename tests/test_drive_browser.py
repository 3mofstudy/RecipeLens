"""雲端資料夾瀏覽視窗：列出、進入、上一層、新增資料夾與選定，Drive API 以模擬物件代替。"""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from src import drive_browser

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
        self.root = tk.Tk()
        self.root.withdraw()
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
        self.root.destroy()
        self.tmp.cleanup()

    def names(self, dialog):
        return [dialog.children[item]["name"] for item in dialog.tree.get_children()]

    def select(self, dialog, name):
        for item, folder in dialog.children.items():
            if folder["name"] == name:
                dialog.tree.selection_set(item)
                dialog.tree.update()
                return

    def test_navigate_up_and_down(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object())
        self.assertEqual(sorted(self.names(dialog)), ["09.我的食譜", "工作"])
        self.assertIn("disabled", dialog.up_button.state())
        self.select(dialog, "09.我的食譜")
        dialog.open_selected()
        self.assertEqual(self.names(dialog), ["湯品"])
        self.assertEqual(dialog.location.get(), "我的雲端硬碟 > 09.我的食譜")
        dialog.go_up()
        self.assertEqual(dialog.location.get(), "我的雲端硬碟")
        dialog.cancel()

    def test_start_in_last_folder(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object(), start_folder="c")
        self.assertEqual(dialog.location.get(), "我的雲端硬碟 > 09.我的食譜 > 湯品")
        dialog.cancel()

    def test_new_folder_is_created_and_selected(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object(), start_folder="a")
        with patch.object(drive_browser.simpledialog, "askstring", return_value="甜點"):
            dialog.new_folder()
        self.assertIn("甜點", self.names(dialog))
        self.assertEqual(dialog.selected_target()["name"], "甜點")
        self.assertEqual(self.drive.items["new1"]["parents"], ["a"])
        dialog.cancel()

    def test_choose_selected_or_current_folder(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object(), start_folder="a")
        dialog.choose()
        self.assertEqual(dialog.result["id"], "a")
        self.assertEqual(drive_browser.last_folder_id(), "a")
        dialog = drive_browser.DriveFolderDialog(self.root, object(), start_folder="a")
        self.select(dialog, "湯品")
        dialog.choose()
        self.assertEqual(dialog.result["id"], "c")
        self.assertEqual([p["name"] for p in dialog.result["path"]], ["我的雲端硬碟", "09.我的食譜", "湯品"])

    def test_cancel_returns_none(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object())
        dialog.cancel()
        self.assertIsNone(dialog.result)

    def test_missing_last_folder_falls_back_to_root(self):
        dialog = drive_browser.DriveFolderDialog(self.root, object(), start_folder="gone")
        self.assertEqual(dialog.location.get(), "我的雲端硬碟")
        dialog.cancel()


if __name__ == "__main__":
    unittest.main(verbosity=2)

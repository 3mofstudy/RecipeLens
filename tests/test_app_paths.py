"""安裝版的路徑：工具在安裝資料夾，設定與食譜在使用者資料夾。"""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import app_paths, environment


class AppPathTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(app_paths)

    def test_source_run_uses_project_folder(self):
        importlib.reload(app_paths)
        project = Path(app_paths.__file__).resolve().parent.parent
        self.assertEqual(app_paths.DATA_ROOT, project)
        self.assertEqual(app_paths.OUTPUT_ROOT, project / "output")

    def test_installed_app_keeps_user_data_outside_install_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "Programs" / "RecipeLens"
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", str(install / "_internal"), create=True), \
                    patch.object(sys, "executable", str(install / "RecipeLens.exe")), \
                    patch.dict(os.environ, {"LOCALAPPDATA": str(root / "Local")}):
                importlib.reload(app_paths)
                self.assertEqual(app_paths.APP_ROOT, install.resolve())
                self.assertEqual(app_paths.RESOURCE_ROOT, install / "_internal")
                self.assertEqual(app_paths.DATA_ROOT, root / "Local" / "RecipeLens")
                self.assertEqual(app_paths.OUTPUT_ROOT.name, "RecipeLens")
                self.assertNotEqual(app_paths.OUTPUT_ROOT.parent, install.resolve())

    def test_installed_tools_win_over_system_path(self):
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            paths = {
                "yt-dlp": install / "tools/yt-dlp.exe",
                "ffmpeg": install / "tools/ffmpeg/bin/ffmpeg.exe",
                "ffprobe": install / "tools/ffmpeg/bin/ffprobe.exe",
                "deno": install / "tools/deno.exe",
            }
            for path in paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with patch.object(environment.sys, "frozen", True, create=True), \
                    patch.object(environment, "APP_ROOT", install), \
                    patch.object(environment.shutil, "which") as system:
                for name, path in paths.items():
                    self.assertEqual(environment.find_tool(name), str(path))
                system.assert_not_called()


if __name__ == "__main__":
    unittest.main()

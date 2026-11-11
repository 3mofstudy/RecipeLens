"""AI 工具環境檢查測試。"""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src.environment import claude_from_desktop_or_standalone, codex_from_desktop_or_standalone, is_app_alias

from src import setup_check


class SetupCheckTest(unittest.TestCase):
    def test_status_uses_provider_tools(self):
        status = setup_check.ai_tool_status(find=lambda name: "C:/codex.exe" if name == "codex" else None)
        self.assertEqual(status, {"Codex": True, "Claude": False})
        self.assertEqual(setup_check.missing_providers(status), ["Claude"])

    def test_summary_when_nothing_installed_requires_one(self):
        text = setup_check.setup_summary({"Codex": False, "Claude": False})
        self.assertIn("至少安裝", text)
        self.assertIn("ChatGPT 桌面版", text)
        self.assertFalse(setup_check.any_installed({"Codex": False, "Claude": False}))

    def test_summary_when_one_installed_allows_entry(self):
        text = setup_check.setup_summary({"Codex": True, "Claude": False})
        self.assertIn("可以進入主畫面", text)
        self.assertTrue(setup_check.any_installed({"Codex": True, "Claude": False}))

    def test_guides_point_to_desktop_apps_and_plans(self):
        codex = setup_check.INSTALL_GUIDES["Codex"]
        claude = setup_check.INSTALL_GUIDES["Claude"]
        self.assertIn("ChatGPT 桌面版", codex.name)
        self.assertIn("9PLM9XGG6VKS", codex.url)
        self.assertEqual(codex.command, "winget install --id 9PLM9XGG6VKS -s msstore")
        self.assertIn("免費", codex.plan)
        self.assertIn("Claude 桌面版", claude.name)
        self.assertEqual(claude.url, "https://claude.com/download")
        self.assertEqual(claude.command, "winget install Anthropic.Claude")
        self.assertIn("付費", claude.plan)
        self.assertIn("Code", claude.steps)

    def test_missing_tool_message_has_link(self):
        message = setup_check.missing_tool_message("Claude")
        self.assertIn(setup_check.INSTALL_GUIDES["Claude"].url, message)


class CodexDesktopDetectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = Path(self.temp.name)
        self.home = patch("src.environment.Path.home", return_value=self.local / "home")
        self.home.start()
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("CODEX_CLI_PATH", None)

    def tearDown(self):
        self.env.stop()
        self.home.stop()
        self.temp.cleanup()

    def make(self, *parts):
        path = self.local.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"exe")
        return path

    def test_none_when_nothing_installed(self):
        self.assertIsNone(codex_from_desktop_or_standalone(self.local))

    def test_desktop_relocated_cli_newest_hash_wins(self):
        old = self.make("OpenAI", "Codex", "bin", "aaaaaaaaaaaaaaaa", "codex.exe")
        new = self.make("OpenAI", "Codex", "bin", "bbbbbbbbbbbbbbbb", "codex.exe")
        self.make("OpenAI", "Codex", "bin", ".staging-cccc-1", "codex.exe")
        os.utime(old, (time.time() - 100, time.time() - 100))
        self.assertEqual(codex_from_desktop_or_standalone(self.local), str(new))

    def test_standalone_cli_preferred_over_desktop(self):
        self.make("OpenAI", "Codex", "bin", "aaaaaaaaaaaaaaaa", "codex.exe")
        standalone = self.make("Programs", "OpenAI", "Codex", "bin", "codex.exe")
        self.assertEqual(codex_from_desktop_or_standalone(self.local), str(standalone))

    def test_codex_cli_path_override(self):
        custom = self.make("custom", "codex.exe")
        os.environ["CODEX_CLI_PATH"] = str(custom)
        self.assertEqual(codex_from_desktop_or_standalone(self.local), str(custom))

    def test_plugin_appserver_fallback(self):
        server = self.make("home", ".codex", "plugins", ".plugin-appserver", "codex.exe")
        self.assertEqual(codex_from_desktop_or_standalone(self.local), str(server))



class ClaudeDesktopDetectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, *parts):
        path = self.home.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"exe")
        return path

    def test_none_when_nothing_installed(self):
        self.assertIsNone(claude_from_desktop_or_standalone(self.home))

    def test_desktop_bundled_highest_version(self):
        self.make("AppData", "Roaming", "Claude", "claude-code", "2.1.99", "claude.exe")
        newest = self.make("AppData", "Roaming", "Claude", "claude-code", "2.1.308", "claude.exe")
        self.assertEqual(claude_from_desktop_or_standalone(self.home), str(newest))

    def test_store_package_location(self):
        store = self.make("AppData", "Local", "Packages", "Claude_pzs8sxrjxfjjc", "LocalCache",
                          "Roaming", "Claude", "claude-code", "2.1.260", "claude.exe")
        self.assertEqual(claude_from_desktop_or_standalone(self.home), str(store))

    def test_standalone_cli_preferred(self):
        self.make("AppData", "Roaming", "Claude", "claude-code", "2.1.308", "claude.exe")
        cli = self.make(".local", "bin", "claude.exe")
        self.assertEqual(claude_from_desktop_or_standalone(self.home), str(cli))

    def test_windowsapps_alias_ignored(self):
        self.assertTrue(is_app_alias("claude", r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\claude.exe"))
        self.assertFalse(is_app_alias("ffmpeg", r"C:\WindowsApps\ffmpeg.exe"))


if __name__ == "__main__":
    unittest.main()

"""Google 官方資料夾 Picker、回環回傳及授權快取的測試。"""
import http.client
import json
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlsplit
import unittest
from unittest.mock import MagicMock, patch

from google_auth_oauthlib.flow import InstalledAppFlow

from src import cloud_upload, google_picker
from src.picker_server import pick_folder_in_browser


class GooglePickerTests(unittest.TestCase):
    def test_picker_checks_folder_permission_before_accepting(self):
        credentials = MagicMock()
        service = MagicMock()
        folder = {
            "id": "folder-a", "name": "食譜", "mimeType": "application/vnd.google-apps.folder",
            "capabilities": {"canAddChildren": True},
        }
        service.files.return_value.get.return_value.execute.return_value = folder
        with (
            patch.object(google_picker, "google_credentials", return_value=credentials),
            patch.object(google_picker, "read_json", side_effect=[
                {"installed": {"client_id": "123-client.apps.googleusercontent.com"}}, {},
            ]),
            patch.object(google_picker, "pick_folder_in_browser", return_value="folder-a"),
            patch.object(google_picker, "build", return_value=service),
            patch.object(google_picker, "write_json") as save,
        ):
            selected_service, selected = google_picker.choose_drive_folder()
        self.assertIs(selected_service, service)
        self.assertEqual(selected["id"], "folder-a")
        self.assertEqual(save.call_args.args[1]["id"], "folder-a")

    def test_cancel_picker_does_not_access_remote_files(self):
        with (
            patch.object(google_picker, "google_credentials"),
            patch.object(google_picker, "read_json", side_effect=[
                {"installed": {"client_id": "123-client.apps.googleusercontent.com"}}, {},
            ]),
            patch.object(google_picker, "pick_folder_in_browser", return_value=None),
            patch.object(google_picker, "build") as build,
        ):
            self.assertIsNone(google_picker.choose_drive_folder())
            build.assert_not_called()

    def test_local_picker_callback_rejects_foreign_origin_and_returns_folder(self):
        observed = {}
        threads = []

        def open_browser(url):
            def browser():
                try:
                    parsed = urlsplit(url)
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                    connection.request("GET", parsed.path + "config")
                    response = connection.getresponse()
                    observed["cache"] = response.getheader("Cache-Control")
                    observed["config"] = json.loads(response.read())
                    connection.close()
                    for origin in ("https://example.org", f"http://{parsed.netloc}"):
                        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                        connection.request("POST", parsed.path + "result",
                                           json.dumps({"action": "picked", "folder_id": "folder-a"}),
                                           {"Origin": origin, "Content-Type": "application/json"})
                        response = connection.getresponse()
                        observed[origin] = response.status
                        response.read()
                        connection.close()
                except Exception as error:
                    observed["error"] = error
            worker = Thread(target=browser)
            threads.append(worker)
            worker.start()
            return True

        selected = pick_folder_in_browser("test-token", "test-project", timeout=5, opener=open_browser)
        for worker in threads:
            worker.join(timeout=5)
        self.assertNotIn("error", observed)
        self.assertEqual(selected, "folder-a")
        self.assertEqual(observed["https://example.org"], 403)
        self.assertEqual(observed["cache"], "no-store")
        self.assertEqual(observed["config"]["access_token"], "test-token")

    def test_login_reuses_valid_cached_credentials(self):
        credentials = MagicMock()
        credentials.valid = True
        credentials.expired = False
        credentials.to_json.return_value = '{"refresh_token":"test"}'
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(cloud_upload, "ensure_client_config"),
            patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=credentials),
            patch.object(InstalledAppFlow, "from_client_secrets_file") as factory,
        ):
            token_file = Path(folder) / "token.json"
            token_file.write_text("{}", encoding="utf-8")
            with patch.object(cloud_upload, "TOKEN_FILE", token_file):
                self.assertIs(cloud_upload.google_credentials(), credentials)
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

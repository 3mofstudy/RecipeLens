"""yt-dlp 下載結果路徑解析測試。"""
import tempfile
import unittest
from pathlib import Path

from src.video_download import downloaded_video


class DownloadedVideoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name) / "我的影片" / ".recipe-lens-abc"
        self.work.mkdir(parents=True)
        self.video = self.work / "source.webm"
        self.video.write_bytes(b"video")

    def tearDown(self):
        self.temp.cleanup()

    def test_garbled_parent_folder_still_finds_video(self):
        printed = "D:\\Lucy\\Downloads\\\ufffd\ufffde\ufffdO\\.recipe-lens-abc\\source.webm"
        self.assertEqual(downloaded_video(self.work, printed), self.video.resolve())

    def test_falls_back_to_scanning_work_folder(self):
        (self.work / "source.info.json").write_text("{}", encoding="utf-8")
        self.assertEqual(downloaded_video(self.work, "\ufffd\ufffd"), self.video.resolve())

    def test_missing_video_raises(self):
        self.video.unlink()
        with self.assertRaises(ValueError):
            downloaded_video(self.work, "source.webm")



class KillActiveProcessesTest(unittest.TestCase):
    def test_running_tool_is_terminated(self):
        import sys
        import threading
        from src import media
        from src.cancellation import JobCancelled
        from threading import Event
        import src.cancellation as cancellation
        event = Event()
        result = {}

        def job():
            cancellation._state.event = event
            try:
                media.run([sys.executable, "-c", "import time; time.sleep(30)"], folder=None, timeout=60)
            except BaseException as error:  # JobCancelled 或結束碼錯誤
                result["error"] = error
            finally:
                cancellation._state.event = None

        worker = threading.Thread(target=job)
        worker.start()
        for _ in range(50):
            if media._ACTIVE:
                break
            threading.Event().wait(0.1)
        self.assertTrue(media._ACTIVE)
        event.set()
        media.kill_active_processes()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(media._ACTIVE)
        self.assertIsInstance(result.get("error"), (JobCancelled, ValueError))


if __name__ == "__main__":
    unittest.main()

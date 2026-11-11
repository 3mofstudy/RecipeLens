"""以本機 Python 子程序驗證取消，不使用外部服務。"""
from pathlib import Path
from queue import Queue
from threading import Event, Thread
import sys
import tempfile
import unittest

from src.cancellation import cancellable_worker
from src.media import run


class CancellationTests(unittest.TestCase):
    def test_running_process_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready"

            class Worker:
                cancel_event = Event()
                events = Queue()

                @cancellable_worker
                def work(self):
                    run([sys.executable, "-c",
                         "from pathlib import Path; import time; "
                         "Path('ready').touch(); time.sleep(30)"],
                        folder=directory)
                    self.events.put(("unexpected", None))

            worker = Worker()
            thread = Thread(target=worker.work, daemon=True)
            thread.start()
            for _ in range(100):
                if ready.exists():
                    break
                worker.cancel_event.wait(0.05)
            worker.cancel_event.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(ready.exists(), "子程序必須確實啟動")
            self.assertEqual(worker.events.get_nowait(), ("cancelled", None))
            self.assertTrue(worker.events.empty())

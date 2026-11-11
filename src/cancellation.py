"""背景工作的合作式取消；不讓使用者中止進入錯誤修復。"""
from contextlib import contextmanager
from functools import wraps
from threading import local

_state = local()


class JobCancelled(BaseException):
    pass


def check_cancelled():
    event = getattr(_state, "event", None)
    if event is not None and event.is_set():
        raise JobCancelled()


def current_event():
    return getattr(_state, "event", None)


def cancellable_worker(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        _state.event = self.cancel_event
        try:
            check_cancelled()
            return function(self, *args, **kwargs)
        except JobCancelled:
            self.events.put(("cancelled", None))
        finally:
            _state.event = None
    return wrapped


@contextmanager
def cancel_scope(event):
    """讓目前執行緒的外部工具受指定事件控制（例如登入視窗的「取消登入」）。"""
    previous = getattr(_state, "event", None)
    _state.event = event
    try:
        yield
    finally:
        _state.event = previous

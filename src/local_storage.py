"""本機紀錄的原子寫入，避免中斷留下不完整的 JSON。"""
import json
from pathlib import Path
import tempfile


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)

"""「更多設定」的預設值，保存在 config/settings.json。"""
from pathlib import Path

from .ai_recipe import AI_PROVIDERS
from .local_storage import read_json, write_json

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"
UPLOAD_FORMATS = ("md", "pdf", "docx")


def default_settings():
    from .recipe_lens import DEFAULT_OUTPUT
    return {
        "provider": "Codex",
        "models": {name: models[0] for name, models in AI_PROVIDERS.items()},
        "output_dir": str(DEFAULT_OUTPUT),
        "upload_after": False,
        "formats": list(UPLOAD_FORMATS),
        "drive_folder": None,   # {"id", "name", "path": ["我的雲端硬碟", ...]}
    }


def load_settings(path=SETTINGS_FILE):
    """讀取已保存的設定；檔案損壞或欄位不合法時改用預設值。"""
    settings = default_settings()
    try:
        saved = read_json(path)
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        return settings
    if saved.get("provider") in AI_PROVIDERS:
        settings["provider"] = saved["provider"]
    models = saved.get("models")
    if isinstance(models, dict):
        for name in AI_PROVIDERS:
            if isinstance(models.get(name), str) and models[name].strip():
                settings["models"][name] = models[name].strip()
    if isinstance(saved.get("output_dir"), str) and saved["output_dir"].strip():
        settings["output_dir"] = saved["output_dir"].strip()
    if isinstance(saved.get("upload_after"), bool):
        settings["upload_after"] = saved["upload_after"]
    if isinstance(saved.get("formats"), list):
        settings["formats"] = [value for value in UPLOAD_FORMATS if value in saved["formats"]]
    folder = saved.get("drive_folder")
    if (isinstance(folder, dict) and isinstance(folder.get("id"), str) and folder["id"]
            and isinstance(folder.get("name"), str) and isinstance(folder.get("path"), list)
            and all(isinstance(part, str) for part in folder["path"])):
        settings["drive_folder"] = {"id": folder["id"], "name": folder["name"], "path": folder["path"]}
    return settings


def save_settings(settings, path=SETTINGS_FILE):
    write_json(path, settings)

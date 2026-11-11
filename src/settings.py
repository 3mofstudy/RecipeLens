"""「更多設定」的預設值，保存在 config/settings.json。"""
from pathlib import Path

from .ai_recipe import AI_PROVIDERS, AUTO_MODEL, RETIRED_MODELS, model_id
from .local_storage import read_json, write_json
from .app_paths import DATA_ROOT

SETTINGS_FILE = DATA_ROOT / "config" / "settings.json"
UPLOAD_FORMATS = ("md", "pdf", "docx")


def default_settings():
    from .recipe_lens import DEFAULT_OUTPUT
    return {
        "provider": "Codex",
        "last_url": "",
        "models": {name: models[0] for name, models in AI_PROVIDERS.items()},
        "output_dir": str(DEFAULT_OUTPUT),
        "auto_upload": False,   # 按「開始下載」後一次跑完：轉換完成直接上傳到事先選好的雲端資料夾
        "formats": list(UPLOAD_FORMATS),
        "local_formats": list(UPLOAD_FORMATS),
        "drive_folder": None,   # {"id", "name", "path": ["我的雲端硬碟", ...]}
        "setup_done": False,    # 首次啟動已通過環境檢查；之後只在一種 AI 都找不到時再檢查
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
    if isinstance(saved.get("last_url"), str):
        settings["last_url"] = saved["last_url"].strip()
    if saved.get("provider") in AI_PROVIDERS:
        settings["provider"] = saved["provider"]
    models = saved.get("models")
    if isinstance(models, dict):
        for name in AI_PROVIDERS:
            if isinstance(models.get(name), str) and models[name].strip():
                value = model_id(models[name])
                # 已停用的模型與舊版「自動」改回預設（最省額度）模型
                settings["models"][name] = (AI_PROVIDERS[name][0] if value in RETIRED_MODELS or value == AUTO_MODEL
                                              else value)
    if isinstance(saved.get("output_dir"), str) and saved["output_dir"].strip():
        settings["output_dir"] = saved["output_dir"].strip()
    if isinstance(saved.get("formats"), list):
        settings["formats"] = [value for value in UPLOAD_FORMATS if value in saved["formats"]]
    if isinstance(saved.get("local_formats"), list):
        settings["local_formats"] = ["md", *(value for value in UPLOAD_FORMATS[1:]
                                               if value in saved["local_formats"])]
    if isinstance(saved.get("setup_done"), bool):
        settings["setup_done"] = saved["setup_done"]
    folder = saved.get("drive_folder")
    if (isinstance(folder, dict) and isinstance(folder.get("id"), str) and folder["id"]
            and isinstance(folder.get("name"), str) and isinstance(folder.get("path"), list)
            and all(isinstance(part, str) for part in folder["path"])):
        settings["drive_folder"] = {"id": folder["id"], "name": folder["name"], "path": folder["path"]}
    # 上傳改為事先選好資料夾、按「開始下載」一次跑完。舊版的 upload_after 不沿用；
    # 舊版勾選「轉換後詢問上傳」且已選過雲端資料夾者，沿用為自動上傳。
    if isinstance(saved.get("auto_upload"), bool):
        settings["auto_upload"] = saved["auto_upload"]
    elif saved.get("ask_upload") is True and settings["drive_folder"]:
        settings["auto_upload"] = True
    return settings


def save_settings(settings, path=SETTINGS_FILE):
    write_json(path, settings)

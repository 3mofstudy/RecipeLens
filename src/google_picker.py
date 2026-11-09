"""使用 Google 官方網頁 Picker 的資料夾選取模式，並沿用桌面登入憑證。"""
from googleapiclient.discovery import build

from .cloud_upload import CLIENT_FILE, CONFIG, google_credentials
from .local_storage import read_json, write_json
from .picker_server import pick_folder_in_browser


def choose_drive_folder():
    """成功回傳 (Drive service, folder)，取消則回傳 None。"""
    credentials = google_credentials()
    client = read_json(CLIENT_FILE)["installed"]
    app_id = client["client_id"].split("-", 1)[0]
    folder_id = pick_folder_in_browser(credentials.token, app_id)
    if folder_id is None:
        return None
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    folder = service.files().get(
        fileId=folder_id, fields="id,name,mimeType,trashed,capabilities(canAddChildren)",
        supportsAllDrives=True,
    ).execute()
    if folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise ValueError("請在 Google 選擇器中選取一個可使用的資料夾。")
    if not folder.get("capabilities", {}).get("canAddChildren"):
        raise ValueError("你沒有在所選 Google 雲端硬碟資料夾新增檔案的權限。")
    write_json(CONFIG / "last_drive_folder.json", {
        "id": folder["id"], "name": folder["name"],
        "url": f"https://drive.google.com/drive/folders/{folder['id']}",
    })
    return service, folder

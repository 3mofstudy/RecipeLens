"""類似檔案總管的 Google 雲端硬碟資料夾選擇視窗。"""

from .cloud_upload import CONFIG, validate_name
from .local_storage import read_json, write_json

FOLDER_MIME = "application/vnd.google-apps.folder"
LAST_FOLDER_FILE = CONFIG / "last_drive_folder.json"


# ---- Drive API 小工具 -------------------------------------------------------

def get_folder(service, folder_id):
    return service.files().get(
        fileId=folder_id, fields="id,name,mimeType,parents,trashed,capabilities(canAddChildren)",
        supportsAllDrives=True,
    ).execute()


def list_child_folders(service, parent_id):
    folders, page = [], None
    while True:
        result = service.files().list(
            q=f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false",
            fields="nextPageToken,files(id,name,modifiedTime)", pageSize=200, pageToken=page,
            orderBy="name_natural", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        folders.extend(result.get("files", []))
        page = result.get("nextPageToken")
        if not page:
            return folders


def create_folder(service, parent_id, name):
    return service.files().create(
        body={"name": validate_name(name), "mimeType": FOLDER_MIME, "parents": [parent_id]},
        fields="id,name,modifiedTime", supportsAllDrives=True,
    ).execute()


def folder_path(service, folder_id):
    """回傳從「我的雲端硬碟」到指定資料夾的 [{id,name}, ...]。"""
    root = get_folder(service, "root")
    chain = []
    current = get_folder(service, folder_id)
    while current["id"] != root["id"]:
        if current.get("trashed") or current.get("mimeType") != FOLDER_MIME:
            raise ValueError("資料夾已不存在。")
        chain.append({"id": current["id"], "name": current["name"]})
        parents = current.get("parents") or []
        if not parents:  # 共用給我的資料夾，沒有可存取的上層
            break
        current = get_folder(service, parents[0])
    else:
        chain.append({"id": root["id"], "name": "我的雲端硬碟"})
    return list(reversed(chain))


from .qt_drive_dialog import DriveFolderDialog


def last_folder_id():
    try:
        return read_json(LAST_FOLDER_FILE).get("id")
    except (OSError, ValueError, AttributeError):
        return None


def choose_folder(parent, service, start_folder=None):
    return DriveFolderDialog(parent, service, start_folder or last_folder_id()).show_selection()

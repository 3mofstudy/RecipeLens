"""類似檔案總管的 Google 雲端硬碟資料夾選擇視窗，範圍限於 App 建立的根資料夾。"""

from .cloud_upload import CONFIG, FOLDER_MIME, app_root_folder, validate_name
from .local_storage import read_json, write_json
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


def folder_path(service, folder_id, root):
    """回傳從 App 根資料夾到指定資料夾的 [{id,name}, ...]。

    drive.file 看不到根資料夾以外的上層，不在根資料夾內就引發 ValueError，由呼叫端改回根資料夾。
    """
    chain = []
    current = get_folder(service, folder_id)
    for _ in range(100):  # 防止異常的循環上層
        if current.get("trashed") or current.get("mimeType") != FOLDER_MIME:
            raise ValueError("資料夾已不存在。")
        chain.append({"id": current["id"], "name": current["name"]})
        if current["id"] == root["id"]:
            return list(reversed(chain))
        parents = current.get("parents") or []
        if not parents:
            break
        current = get_folder(service, parents[0])
    raise ValueError(f"資料夾不在「{root['name']}」內。")


from .qt_drive_dialog import DriveFolderDialog


def last_folder_id():
    try:
        return read_json(LAST_FOLDER_FILE).get("id")
    except (OSError, ValueError, AttributeError):
        return None


def choose_folder(parent, service, start_folder=None):
    return DriveFolderDialog(parent, service, start_folder or last_folder_id()).show_selection()

"""獨立的 Google Drive 上傳入口，保留本機 Markdown、圖片與轉檔。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
from filelock import FileLock

from .document_export import export_documents
from .local_storage import read_json, write_json

CONFIG = Path(__file__).resolve().parent.parent / "config"
CLIENT_FILE = CONFIG / "google_client.json"
TOKEN_FILE = CONFIG / "google_token.json"
# 自製的雲端資料夾瀏覽視窗需要列出使用者全部資料夾，drive.file 只看得到 App 建立的檔案。
SCOPES = ["https://www.googleapis.com/auth/drive"]


def configure_google(client_file):
    data = read_json(client_file)
    installed = data.get("installed", {}) if isinstance(data, dict) else {}
    if (not isinstance(installed, dict) or not installed.get("client_id")
            or not installed.get("client_secret")):
        raise ValueError("請選擇 Google Cloud 下載的「桌面應用程式」OAuth 用戶端 JSON。")
    if CLIENT_FILE.is_file() and read_json(CLIENT_FILE) == data:
        return
    write_json(CLIENT_FILE, data)
    # 換用不同用戶端時，重新進行瀏覽器授權。
    TOKEN_FILE.unlink(missing_ok=True)


def ensure_client_config():
    if CLIENT_FILE.is_file():
        return
    bundled = CONFIG.parent / "data" / "google_client.json"
    if bundled.is_file():
        configure_google(bundled)
        return
    raise ValueError("尚未配置 RecipeLens 的 Google 用戶端。請將開發者下載的桌面 OAuth JSON 放入 data/google_client.json，設定步驟見 readme.md。")


def google_credentials():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    ensure_client_config()
    credentials = None
    if TOKEN_FILE.is_file():
        # 不帶 SCOPES 讀取，才能知道既有授權實際涵蓋哪些權限；權限不足時重新登入。
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE))
        if not credentials.has_scopes(SCOPES):
            credentials = None
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=180,
            authorization_prompt_message="",
            success_message="Google 授權完成，請關閉這個分頁並返回 RecipeLens。",
        )
    write_json(TOKEN_FILE, json.loads(credentials.to_json()))
    return credentials


def google_service():
    from googleapiclient.discovery import build
    credentials = google_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def list_folders(service):
    """僅列出目前 Google 授權允許 RecipeLens 存取的資料夾。"""
    folders = []
    page = None
    while True:
        result = service.files().list(
            q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="nextPageToken,files(id,name)", pageSize=100, pageToken=page,
            orderBy="name",
        ).execute()
        folders.extend(result.get("files", []))
        page = result.get("nextPageToken")
        if not page:
            return folders


def validate_name(name):
    name = name.strip()
    if not name or any(character in name for character in ("/", "\\", "\n", "\r", "\0")):
        raise ValueError("名稱不可空白，亦不可包含斜線或換行。")
    return name


def destination_folder(service, parent_id, name, journal):
    """為新資料夾預配 ID 並保留紀錄，支援建立後連線中斷的重試。"""
    from googleapiclient.errors import HttpError

    name = validate_name(name)
    with FileLock(str(journal) + ".lock", timeout=10):
        state = read_json(journal)
        key = json.dumps([parent_id, name], ensure_ascii=False)
        if key not in state:
            file_id = service.files().generateIds(count=1, space="drive").execute()["ids"][0]
            state[key] = {"id": file_id}
            write_json(journal, state)
        file_id = state[key]["id"]
        try:
            remote = service.files().get(
                fileId=file_id, fields="id,trashed", supportsAllDrives=True,
            ).execute()
            if remote.get("trashed"):
                raise ValueError("先前建立的資料夾在垃圾桶，請先還原或使用其他資料夾名稱。")
        except HttpError as error:
            if error.resp.status != 404:
                raise
            service.files().create(body={
                "id": file_id, "name": name, "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }, fields="id", supportsAllDrives=True).execute()
        return file_id


def upload_files(files, service, journal, *, parent_id=None, file_stem=None):
    """先記錄預配的 Drive ID，再上傳，回應遺失時可使用相同 ID 重試。"""
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(journal) + ".lock", timeout=10):
        return _upload_files(files, service, journal, parent_id, file_stem)


def _upload_files(files, service, journal, parent_id, file_stem):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseUpload

    state = read_json(journal)
    completed = []
    mime_types = {
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    if file_stem is not None:
        file_stem = validate_name(file_stem)
    for file in files:
        file = Path(file)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        name = f"{file_stem}{file.suffix}" if file_stem is not None else file.name
        key = f"{file.suffix}:{digest}"
        if parent_id not in (None, "root") or name != file.name:
            key = json.dumps([parent_id or "root", name, key], ensure_ascii=False)
        entry = state.get(key)
        try:
            if entry is None:
                file_id = service.files().generateIds(count=1, space="drive").execute()["ids"][0]
                entry = {"id": file_id, "name": name}
                state[key] = entry
                write_json(journal, state)
            remote = None
            try:
                remote = service.files().get(
                    fileId=entry["id"], fields="id,name,webViewLink,trashed",
                    supportsAllDrives=True,
                ).execute()
            except HttpError as error:
                if error.resp.status != 404:
                    raise
            if remote and remote.get("trashed"):
                raise ValueError("先前上傳的檔案在雲端垃圾桶，請先還原該檔案再重試。")
            if remote is None:
                with file.open("rb") as stream:
                    metadata = {"id": entry["id"], "name": name}
                    if parent_id:
                        metadata["parents"] = [parent_id]
                    request = service.files().create(
                        body=metadata,
                        media_body=MediaIoBaseUpload(
                            stream, mimetype=mime_types[file.suffix], resumable=True,
                        ),
                        fields="id,name,webViewLink",
                        supportsAllDrives=True,
                    )
                    while remote is None:
                        _, remote = request.next_chunk(num_retries=3)
            entry["url"] = remote.get("webViewLink") or f"https://drive.google.com/file/d/{entry['id']}/view"
            write_json(journal, state)
            completed.append(dict(entry))
        except Exception as error:
            done = "、".join(item["name"] for item in completed) or "尚無"
            raise RuntimeError(
                f"上傳 {file.name} 失敗，已完成：{done}。本機檔案及上傳紀錄已保留，可再次上傳重試。\n{error}"
            ) from error
    return completed


IMAGE_LINK = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")


def markdown_images(markdown):
    """列出 Markdown 引用的本機圖片，依出現順序且不重複。"""
    markdown = Path(markdown).resolve()
    images = []
    for _, link, _ in IMAGE_LINK.findall(markdown.read_text(encoding="utf-8")):
        if "://" in link:
            continue
        image = (markdown.parent / unquote(link)).resolve()
        if image.is_relative_to(markdown.parent) and image.is_file() and image not in images:
            images.append(image)
    return images


def markdown_for_drive(markdown, folder_name):
    """產生雲端用 Markdown 副本，圖片連結指向同層的雲端圖片資料夾，本機原檔不變。"""
    markdown = Path(markdown).resolve()
    text = markdown.read_text(encoding="utf-8")

    def relink(match):
        link = match.group(2)
        image = (markdown.parent / unquote(link)).resolve()
        if "://" in link or not image.is_file():
            return match.group(0)
        return f"{match.group(1)}{folder_name}/{image.name}{match.group(3)}"

    target = markdown.parent / ".drive" / markdown.name
    target.parent.mkdir(exist_ok=True)
    target.write_text(IMAGE_LINK.sub(relink, text), encoding="utf-8")
    return target


def upload_recipe(markdown, formats=("pdf",), *, service=None, progress=print,
                  parent_id=None, file_stem=None, new_folder=None, include_images=True):
    """上傳 .md 時一併上傳圖片。

    指定 new_folder（每份食譜自己的資料夾）時，圖片放在其中的 images 資料夾，
    與本機結構相同；否則放在同層的「檔名_images」資料夾。
    """
    if file_stem is not None:
        file_stem = validate_name(file_stem)
    if new_folder is not None:
        new_folder = validate_name(new_folder)
    progress("正在建立上傳用的文件，本機食譜與圖片會保留…")
    markdown = Path(markdown).resolve()
    files = export_documents(markdown, formats, output_dir=markdown.parent)
    images = markdown_images(markdown) if include_images and "md" in formats else []
    image_folder = "images" if new_folder is not None else f"{file_stem or markdown.stem}_images"
    if images:
        drive_copy = markdown_for_drive(markdown, image_folder)
        files = [drive_copy if file == markdown else file for file in files]
    progress("正在連線至 Google 雲端硬碟，首次使用請完成瀏覽器登入…")
    if service is None:
        service = google_service()
    result = []
    if new_folder is not None:
        progress(f"正在建立雲端食譜資料夾「{new_folder}」…")
        parent_id = destination_folder(
            service, parent_id or "root", new_folder, markdown.parent / "drive-folders.json",
        )
        result.append({"id": parent_id, "name": f"{new_folder}／（食譜資料夾）", "folder": True,
                       "url": f"https://drive.google.com/drive/folders/{parent_id}"})
    journal = markdown.parent / "drive-uploads.json"
    if images:
        progress(f"正在上傳 {len(images)} 張圖片至雲端資料夾「{image_folder}」…")
        folder_id = destination_folder(
            service, parent_id or "root", image_folder, markdown.parent / "drive-folders.json",
        )
        upload_files(images, service, journal, parent_id=folder_id)
        images_entry = {"id": folder_id, "name": f"{image_folder}／（{len(images)} 張圖片）",
                        "url": f"https://drive.google.com/drive/folders/{folder_id}"}
    else:
        images_entry = None
    progress("正在上傳文件至 Google 雲端硬碟…")
    result += upload_files(files, service, journal, parent_id=parent_id, file_stem=file_stem)
    return result + ([images_entry] if images_entry else [])


def main():
    parser = argparse.ArgumentParser(description="將本機食譜轉檔後上傳到 Google 雲端硬碟。")
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--format", choices=["md", "pdf", "docx", "both", "all"], default="pdf")
    parser.add_argument("--formats", nargs="+", choices=["md", "pdf", "docx"],
                        help="複選格式，例如 --formats md docx")
    parser.add_argument("--client-secrets", type=Path, help="首次設定的 Google 桌面 OAuth JSON")
    parser.add_argument("--folder-id", help="雲端父資料夾 ID，省略時使用我的雲端硬碟")
    parser.add_argument("--new-folder", help="在父資料夾內建立的資料夾名稱")
    parser.add_argument("--name", help="雲端檔名，不含副檔名")
    args = parser.parse_args()
    try:
        if args.client_secrets:
            configure_google(args.client_secrets)
        presets = {"both": ("pdf", "docx"), "all": ("md", "pdf", "docx")}
        formats = tuple(args.formats) if args.formats else presets.get(args.format, (args.format,))
        result = upload_recipe(args.markdown, formats, parent_id=args.folder_id,
                               file_stem=args.name, new_folder=args.new_folder)
        for item in result:
            print(f"{item['name']}：{item['url']}")
    except Exception as error:
        parser.exit(1, f"上傳失敗：{error}\n")


if __name__ == "__main__":
    main()

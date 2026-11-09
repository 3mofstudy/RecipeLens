"""類似檔案總管的 Google 雲端硬碟資料夾選擇視窗。"""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

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


# ---- 圖示（以程式繪製，不依賴 emoji 字型） ----------------------------------------

def _icon(root, pixels):
    image = tk.PhotoImage(master=root, width=16, height=16)
    for color, (x1, y1, x2, y2) in pixels:
        image.put(color, to=(x1, y1, x2, y2))
    return image


def make_icons(root):
    body, tab, edge = "#F4C542", "#E0A800", "#B8860B"
    folder = [(edge, (1, 3, 7, 6)), (tab, (2, 4, 6, 6)), (edge, (1, 5, 15, 14)), (body, (2, 6, 14, 13))]
    up = [("#2F6FD6", (6, 7, 10, 15))] + [("#2F6FD6", (8 - i, 1 + i, 8 + i, 2 + i)) for i in range(1, 7)]
    plus = [("#1E8E3E", (10, 7, 12, 14)), ("#1E8E3E", (8, 9, 15, 11))]
    refresh = [("#555555", (3, 3, 13, 5)), ("#555555", (3, 11, 13, 13)), ("#555555", (3, 3, 5, 13)),
               ("#555555", (11, 3, 13, 8)), ("#555555", (9, 7, 15, 9))]
    return {
        "folder": _icon(root, folder),
        "up": _icon(root, up),
        "new": _icon(root, folder + plus),
        "refresh": _icon(root, refresh),
    }


# ---- 視窗 ---------------------------------------------------------------------

class DriveFolderDialog:
    """強制回應視窗；show() 回傳選定的資料夾 dict（id、name、path），取消回傳 None。"""

    def __init__(self, parent, service, start_folder=None):
        self.service = service
        self.result = None
        self.path = []          # [{id, name}]，最後一個是目前所在資料夾
        self.children = {}      # Treeview item id -> folder dict
        self.window = window = tk.Toplevel(parent)
        window.title("選擇 Google 雲端硬碟存放資料夾")
        window.geometry("640x460")
        window.minsize(480, 320)
        window.transient(parent)
        self.icons = make_icons(window)

        toolbar = ttk.Frame(window, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")
        self.up_button = ttk.Button(toolbar, image=self.icons["up"], text="上一層", compound="left",
                                    command=self.go_up)
        self.up_button.pack(side="left")
        ttk.Button(toolbar, image=self.icons["new"], text="新增資料夾", compound="left",
                   command=self.new_folder).pack(side="left", padx=6)
        ttk.Button(toolbar, image=self.icons["refresh"], text="重新整理", compound="left",
                   command=self.refresh).pack(side="left")

        self.location = tk.StringVar()
        address = ttk.Frame(window, padding=(8, 0, 8, 4))
        address.pack(fill="x")
        ttk.Label(address, text="位置：").pack(side="left")
        ttk.Entry(address, textvariable=self.location, state="readonly").pack(side="left", fill="x", expand=True)

        body = ttk.Frame(window, padding=(8, 0, 8, 0))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("modified",), selectmode="browse")
        self.tree.heading("#0", text="名稱", anchor="w")
        self.tree.heading("modified", text="修改日期", anchor="w")
        self.tree.column("#0", width=420)
        self.tree.column("modified", width=150, stretch=False)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)
        self.tree.bind("<BackSpace>", lambda _: self.go_up())
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_target())

        self.target = tk.StringVar()
        footer = ttk.Frame(window, padding=8)
        footer.pack(fill="x")
        ttk.Label(footer, text="雙擊資料夾可進入；選取資料夾後按「上傳到這裡」存入該資料夾，"
                  "沒選取則存入目前位置。", foreground="#666", wraplength=600).pack(anchor="w")
        ttk.Label(footer, textvariable=self.target, wraplength=600).pack(anchor="w", pady=(4, 6))
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="上傳到這裡", command=self.choose).pack(side="right", padx=6)

        window.protocol("WM_DELETE_WINDOW", self.cancel)
        window.bind("<Escape>", lambda _: self.cancel())
        self.start(start_folder)

    # -- 導覽
    def start(self, start_folder):
        try:
            if start_folder:
                self.path = folder_path(self.service, start_folder)
            else:
                raise ValueError
        except Exception:
            root = get_folder(self.service, "root")
            self.path = [{"id": root["id"], "name": "我的雲端硬碟"}]
        self.refresh()

    def busy(self, on):
        self.window.configure(cursor="watch" if on else "")
        self.window.update_idletasks()

    def refresh(self):
        self.busy(True)
        try:
            folders = list_child_folders(self.service, self.path[-1]["id"])
        except Exception as error:
            messagebox.showerror("無法讀取資料夾", str(error), parent=self.window)
            folders = []
        finally:
            self.busy(False)
        self.tree.delete(*self.tree.get_children())
        self.children = {}
        for folder in folders:
            modified = (folder.get("modifiedTime") or "")[:16].replace("T", " ")
            item = self.tree.insert("", "end", text=" " + folder["name"], image=self.icons["folder"],
                                    values=(modified,))
            self.children[item] = folder
        self.location.set(" > ".join(part["name"] for part in self.path))
        self.up_button.state(["!disabled"] if len(self.path) > 1 else ["disabled"])
        self.update_target()

    def enter(self, folder):
        self.path.append({"id": folder["id"], "name": folder["name"]})
        self.refresh()

    def open_selected(self, *_):
        selection = self.tree.selection()
        if selection:
            self.enter(self.children[selection[0]])

    def go_up(self):
        if len(self.path) > 1:
            self.path.pop()
            self.refresh()

    def selected_target(self):
        selection = self.tree.selection()
        if selection:
            folder = self.children[selection[0]]
            return {"id": folder["id"], "name": folder["name"],
                    "path": [*self.path, {"id": folder["id"], "name": folder["name"]}]}
        current = self.path[-1]
        return {"id": current["id"], "name": current["name"], "path": list(self.path)}

    def update_target(self):
        target = self.selected_target()
        self.target.set("存放位置：" + " > ".join(part["name"] for part in target["path"]))

    # -- 動作
    def new_folder(self):
        name = simpledialog.askstring("新增資料夾", f"在「{self.path[-1]['name']}」中新增資料夾：",
                                      initialvalue="新資料夾", parent=self.window)
        if name is None:
            return
        try:
            self.busy(True)
            created = create_folder(self.service, self.path[-1]["id"], name)
        except Exception as error:
            messagebox.showerror("無法新增資料夾", str(error), parent=self.window)
            return
        finally:
            self.busy(False)
        self.refresh()
        for item, folder in self.children.items():
            if folder["id"] == created["id"]:
                self.tree.selection_set(item)
                self.tree.see(item)

    def choose(self):
        target = self.selected_target()
        try:
            folder = get_folder(self.service, target["id"])
        except Exception as error:
            messagebox.showerror("無法使用這個資料夾", str(error), parent=self.window)
            return
        if not folder.get("capabilities", {}).get("canAddChildren", True):
            messagebox.showerror("沒有權限", "你沒有在這個資料夾新增檔案的權限，請選擇其他資料夾。",
                                 parent=self.window)
            return
        self.result = target
        try:
            write_json(LAST_FOLDER_FILE, {
                "id": target["id"], "name": target["name"],
                "url": f"https://drive.google.com/drive/folders/{target['id']}",
            })
        except OSError:
            pass
        self.window.destroy()

    def cancel(self):
        self.result = None
        self.window.destroy()

    def show(self):
        self.window.grab_set()
        self.window.focus_force()
        self.window.wait_window()
        return self.result


def last_folder_id():
    try:
        return read_json(LAST_FOLDER_FILE).get("id")
    except (OSError, ValueError, AttributeError):
        return None


def choose_folder(parent, service, start_folder=None):
    return DriveFolderDialog(parent, service, start_folder or last_folder_id()).show()

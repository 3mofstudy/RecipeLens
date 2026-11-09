"""RecipeLens Windows GUI，背景工作透過佇列回報主執行緒。"""
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .ai_recipe import AI_PROVIDERS, claude_login
from .environment import find_tool
import sys
import webbrowser
from .recipe_lens import DEFAULT_OUTPUT, convert_video
from .settings import SETTINGS_FILE, UPLOAD_FORMATS, load_settings, save_settings
from .video_download import detect_platform
from .media import SPEECH_LANGUAGES
from .cloud_upload import google_service, upload_recipe, validate_name
from .drive_browser import choose_folder
from .document_export import validate_filename


class RecipeLensApp:
    def __init__(self, root, settings_file=SETTINGS_FILE):
        self.root = root
        self.events = Queue()
        self.busy = False
        self.result = None
        self.pending_upload = None
        self.settings_file = settings_file
        settings = load_settings(settings_file)
        root.title("RecipeLens 影片食譜")
        apply_icon(root)
        root.minsize(760, 0)
        style = ttk.Style(root)
        style.configure("Start.TButton", font=("Microsoft JhengHei", 16, "bold"), padding=(48, 12))
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        self.url = tk.StringVar()
        self.platform = tk.StringVar(value="Facebook")
        self.subtitle_mode = tk.StringVar(value="original")
        self.speech_language = tk.StringVar(value="國語")
        self.keep = tk.BooleanVar(value=False)
        self.file_name = tk.StringVar()
        self.status = tk.StringVar(value="貼上影片網址，確認選項後按「開始下載」。")
        # 更多設定（進階選項），預設值由 config/settings.json 載入
        self.models = dict(settings["models"])
        self.provider = tk.StringVar(value=settings["provider"])
        self.model = tk.StringVar(value=self.models[settings["provider"]])
        self.output_dir = tk.StringVar(value=settings["output_dir"])
        self.upload_after = tk.BooleanVar(value=settings["upload_after"])
        self.cloud_formats = {suffix: tk.BooleanVar(value=suffix in settings["formats"])
                              for suffix in UPLOAD_FORMATS}
        self.drive_folder = settings["drive_folder"]
        self.drive_location = tk.StringVar(value=format_location(self.drive_folder))
        self.drive_service = None
        self.advanced_visible = False

        ttk.Label(frame, text="影片網址").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=6)
        ttk.Entry(row, textvariable=self.url).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="貼上網址", command=self.paste).pack(side="left", padx=6)
        self.url.trace_add("write", self.detect)
        ttk.Label(frame, text="1. 確認影片平台（貼上網址後會自動預選）").pack(anchor="w", pady=(12, 4))
        ttk.Combobox(frame, textvariable=self.platform, values=["Facebook", "YouTube"],
                     state="readonly", width=18).pack(anchor="w")
        ttk.Label(frame, text="2. 字幕資訊").pack(anchor="w", pady=(12, 4))
        for text, value in [
            ("沒有原始字幕檔，影片內有內嵌字幕", "embedded"),
            ("沒有原始字幕檔，影片內無內嵌字幕", "none"),
            ("應該有字幕檔，請程式自動檢查下載", "original"),
        ]:
            ttk.Radiobutton(frame, text=text, variable=self.subtitle_mode, value=value,
                            command=self.update_subtitles).pack(anchor="w")
        speech_row = ttk.Frame(frame)
        speech_row.pack(fill="x", pady=6)
        ttk.Label(speech_row, text="無字幕影片的語音語言").pack(side="left")
        self.speech_combo = ttk.Combobox(
            speech_row, textvariable=self.speech_language, values=SPEECH_LANGUAGES,
            state="disabled", width=12,
        )
        self.speech_combo.pack(side="left", padx=8)
        self.speech_note = tk.StringVar()
        ttk.Label(frame, textvariable=self.speech_note, wraplength=700).pack(anchor="w")
        self.speech_language.trace_add("write", self.update_speech_note)
        self.keep_button = ttk.Checkbutton(
            frame, text="3. 在 Markdown 保留完整字幕文字", variable=self.keep,
        )
        self.keep_button.pack(anchor="w", pady=6)
        ttk.Label(frame, text="程式會自行取得字幕；無法取得時改用語音轉錄並標示來源。").pack(anchor="w")
        name_row = ttk.Frame(frame)
        name_row.pack(fill="x", pady=(12, 2))
        ttk.Label(name_row, text="檔案名稱（選填，不含副檔名）").pack(side="left")
        ttk.Entry(name_row, textvariable=self.file_name).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(frame, text="留空時由 AI 判讀食譜名，以「平台-食譜名」命名，例如 FB-蔥爆豬肉、YT-蔥爆豬肉。"
                  ).pack(anchor="w")

        self.more_button = ttk.Button(frame, text="更多設定 ▼", command=self.toggle_advanced)
        self.more_button.pack(anchor="w", pady=(12, 4))
        self.advanced = ttk.LabelFrame(frame, text="進階選項（按「開始下載」時保存為下次的預設值）",
                                       padding=10)
        self.build_advanced(self.advanced)

        self.start_button = ttk.Button(frame, text="開始下載", style="Start.TButton",
                                       command=self.start)
        self.start_button.pack(pady=(16, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=700).pack(anchor="w", pady=8)
        self.update_subtitles()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(150, self.poll)

    def build_advanced(self, box):
        ai_row = ttk.Frame(box)
        ai_row.pack(fill="x", pady=4)
        ttk.Label(ai_row, text="AI 模型").pack(side="left")
        self.provider_combo = ttk.Combobox(ai_row, textvariable=self.provider, values=list(AI_PROVIDERS),
                                           state="readonly", width=10)
        self.provider_combo.pack(side="left", padx=8)
        self.provider_combo.bind("<<ComboboxSelected>>", self.change_provider)
        self.model_combo = ttk.Combobox(ai_row, textvariable=self.model, width=28,
                                        values=AI_PROVIDERS[self.provider.get()])
        self.model_combo.pack(side="left")
        self.login_button = ttk.Button(ai_row, text="登入 Claude 帳號", command=self.login_claude)
        self.update_login_button()
        output_row = ttk.Frame(box)
        output_row.pack(fill="x", pady=(10, 4))
        ttk.Label(output_row, text="本機輸出位置").pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(output_row, text="瀏覽…", command=self.browse_output).pack(side="left")
        ttk.Button(output_row, text="還原預設", command=self.reset_output).pack(side="left", padx=(6, 0))
        ttk.Label(box, text="每份食譜存成一個資料夾，內含 MD、PDF、DOCX 與 images 截圖。").pack(anchor="w")
        ttk.Checkbutton(box, text="下載轉換完成後，不再詢問，直接上傳到下方的雲端存放位置",
                        variable=self.upload_after).pack(anchor="w", pady=(10, 4))
        format_row = ttk.Frame(box)
        format_row.pack(fill="x", pady=4)
        ttk.Label(format_row, text="上傳格式").pack(side="left")
        for suffix, label in (("md", ".md（含 images 資料夾與圖片）"), ("pdf", "PDF"), ("docx", "DOCX")):
            ttk.Checkbutton(format_row, text=label, variable=self.cloud_formats[suffix]).pack(side="left", padx=8)
        ttk.Button(format_row, text="全部選取", command=self.select_all_formats).pack(side="left", padx=8)
        folder_row = ttk.Frame(box)
        folder_row.pack(fill="x", pady=4)
        ttk.Label(folder_row, text="雲端存放位置（根目錄）").pack(side="left")
        ttk.Entry(folder_row, textvariable=self.drive_location, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8)
        self.drive_button = ttk.Button(folder_row, text="選擇…", command=self.pick_drive_folder)
        self.drive_button.pack(side="left")

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced.pack(fill="x", pady=4, after=self.more_button)
            self.more_button.configure(text="更多設定 ▲")
        else:
            self.advanced.pack_forget()
            self.more_button.configure(text="更多設定 ▼")
        self.root.geometry("")

    def update_login_button(self):
        if self.provider.get() == "Claude":
            self.login_button.pack(side="left", padx=8)
        else:
            self.login_button.pack_forget()

    def login_claude(self):
        """在背景執行 `claude auth login`，由瀏覽器登入月租帳號，不開命令視窗。"""
        claude = find_tool("claude")
        if not claude:
            messagebox.showerror("找不到 Claude Code",
                                 "請先安裝 Claude Code，在 PowerShell 執行：\n"
                                 "irm https://claude.ai/install.ps1 | iex\n\n安裝後重新開啟 RecipeLens。")
            return
        if self.busy:
            return
        self.set_busy(True)
        self.status.set("正在開啟瀏覽器登入 Claude，請用有 Pro／Max 月租的帳號登入…")
        Thread(target=self.login_worker, args=(claude,), daemon=True).start()

    def login_worker(self, claude):
        try:
            claude_login(claude)  # 按鈕一律重新登入，可修復過期的登入
            self.events.put(("logged_in", None))
        except Exception as error:
            self.events.put(("error", str(error)))

    def change_provider(self, *_):
        self.update_login_button()
        provider = self.provider.get()
        self.model_combo.configure(values=AI_PROVIDERS[provider])
        self.model.set(self.models.get(provider) or AI_PROVIDERS[provider][0])

    def browse_output(self):
        folder = filedialog.askdirectory(parent=self.root, title="選擇本機輸出位置",
                                         initialdir=self.output_dir.get() or str(DEFAULT_OUTPUT))
        if folder:
            self.output_dir.set(str(Path(folder)))

    def reset_output(self):
        self.output_dir.set(str(DEFAULT_OUTPUT))

    def current_settings(self):
        self.models[self.provider.get()] = self.model.get().strip()
        return {
            "provider": self.provider.get(),
            "models": dict(self.models),
            "output_dir": self.output_dir.get().strip(),
            "upload_after": self.upload_after.get(),
            "formats": [suffix for suffix, variable in self.cloud_formats.items() if variable.get()],
            "drive_folder": self.drive_folder,
        }

    def paste(self):
        try:
            self.url.set(self.root.clipboard_get().strip())
        except tk.TclError:
            messagebox.showinfo("剪貼簿", "剪貼簿沒有可貼上的文字。")

    def detect(self, *_):
        try:
            self.platform.set(detect_platform(self.url.get()))
        except ValueError:
            pass

    def update_subtitles(self):
        self.speech_combo.configure(
            state="readonly" if self.subtitle_mode.get() == "none" else "disabled",
        )
        self.update_speech_note()
        state = "normal" if self.subtitle_mode.get() == "original" else "disabled"
        self.keep_button.configure(state=state)
        if state == "disabled":
            self.keep.set(False)

    def update_speech_note(self, *_):
        note = ""
        if self.subtitle_mode.get() == "none":
            language = self.speech_language.get()
            if language == "其他":
                note = "其他語言由語音模型自動偵測。"
            elif language == "閩南語":
                note = "閩南語以中文辨識加台語提示輔助，辨識結果需核對。首次使用會下載較大模型。"
            elif language == "粵語":
                note = "粵語使用專用語言代碼。首次使用會下載較大模型。"
        self.speech_note.set(note)

    def start(self):
        if self.busy:
            return
        url = self.url.get().strip()
        try:
            if detect_platform(url) != self.platform.get():
                raise ValueError("平台選項與網址不符，請重新確認。")
        except ValueError as error:
            messagebox.showerror("請確認輸入", str(error))
            return
        try:
            file_stem = validate_filename(self.file_name.get()) if self.file_name.get().strip() else None
            formats = tuple(suffix for suffix, variable in self.cloud_formats.items() if variable.get())
            if self.upload_after.get() and not formats:
                raise ValueError("請至少勾選一種上傳格式。")
            if not self.output_dir.get().strip():
                raise ValueError("請在「更多設定」指定本機輸出位置。")
            output = Path(self.output_dir.get().strip()).expanduser()
            if not output.is_absolute():
                raise ValueError("本機輸出位置請填寫完整路徑，例如 C:\\Users\\User\\Documents\\食譜。")
            if output.exists() and not output.is_dir():
                raise ValueError("本機輸出位置不是資料夾，請重新選擇。")
        except ValueError as error:
            messagebox.showerror("請確認設定", str(error))
            return
        options = dict(platform=self.platform.get(), subtitle_mode=self.subtitle_mode.get(),
                       keep_subtitles=self.keep.get(),
                       speech_language=(self.speech_language.get()
                                        if self.subtitle_mode.get() == "none" else "其他"),
                       model=self.model.get().strip() or None, file_stem=file_stem,
                       provider=self.provider.get(), output=output)
        try:
            save_settings(self.current_settings(), self.settings_file)
        except OSError:
            pass  # 無法保存預設值不影響本次轉換
        # 轉換成功後詢問是否上傳；勾選「不再詢問」時直接上傳到雲端存放位置。
        self.pending_upload = {"formats": formats, "ask": not self.upload_after.get()}
        self.busy = True
        self.start_button.configure(state="disabled")
        self.status.set("開始處理…")
        Thread(target=self.worker, args=(url, options), daemon=True).start()

    def worker(self, url, options):
        try:
            result = convert_video(url, progress=lambda text: self.events.put(("progress", text)), **options)
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", str(error)))

    def select_all_formats(self):
        for variable in self.cloud_formats.values():
            variable.set(True)

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.start_button.configure(state=state)
        self.drive_button.configure(state=state)

    def set_drive_folder(self, folder):
        """記住選定的雲端資料夾並保存為預設值。"""
        names = [part["name"] if isinstance(part, dict) else part for part in folder.get("path", [])]
        self.drive_folder = {"id": folder["id"], "name": folder["name"], "path": names or [folder["name"]]}
        self.drive_location.set(format_location(self.drive_folder))
        try:
            save_settings(self.current_settings(), self.settings_file)
        except OSError:
            pass

    def pick_drive_folder(self):
        if not self.busy:
            self.connect("settings")

    def after_conversion(self, source, formats, ask=True):
        source = Path(source)
        if ask:
            choice = ask_upload(self.root, source, self.drive_folder)
        else:
            choice = "upload"
        if choice == "no":
            self.status.set(f"轉換完成：{source.stem}。未上傳，資料只保留在本機：{source.parent}")
            return
        if not formats:
            messagebox.showerror("請選擇上傳格式", "請先在「更多設定」勾選至少一種上傳格式，本機檔案已保留。",
                                 parent=self.root)
            return
        change = choice == "change" or not self.drive_folder
        self.connect("upload", {"source": source, "formats": formats, "change": change})

    def connect(self, purpose, payload=None):
        if self.busy:
            return
        self.set_busy(True)
        self.status.set("正在連線 Google 雲端硬碟…首次使用或權限更新時，請在瀏覽器完成登入。")
        Thread(target=self.connect_worker, args=(purpose, payload), daemon=True).start()

    def connect_worker(self, purpose, payload=None):
        try:
            service = self.drive_service or google_service()
            self.events.put(("drive_ready", (purpose, payload, service)))
        except Exception as error:
            self.events.put(("error", f"無法連線 Google 雲端硬碟，本機檔案已保留。\n{error}"))

    def browse_drive(self, service):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        try:
            return choose_folder(self.root, service, (self.drive_folder or {}).get("id"))
        except Exception as error:
            messagebox.showerror("無法開啟雲端資料夾", str(error), parent=self.root)
            return None

    def drive_ready(self, purpose, payload, service):
        self.drive_service = service
        if purpose == "settings":
            self.status.set("請在視窗中選擇雲端存放位置。")
            folder = self.browse_drive(service)
            self.set_busy(False)
            if folder:
                self.set_drive_folder(folder)
                self.status.set(f"雲端存放位置已設為：{self.drive_location.get()}")
            else:
                self.status.set("未變更雲端存放位置。")
            return
        source, formats = payload["source"], payload["formats"]
        if payload["change"]:
            self.status.set("請在視窗中選擇雲端存放位置。")
            folder = self.browse_drive(service)
            if folder is None:
                self.set_busy(False)
                self.status.set("已取消上傳，本機 MD、PDF、DOCX 與圖片已保留。")
                return
            self.set_drive_folder(folder)
        folder = dict(self.drive_folder)
        # 每份食譜在根目錄下自動建立自己的資料夾；根目錄已由 set_drive_folder 記住。
        destination = {"file_stem": source.stem, "new_folder": source.stem}
        self.status.set(f"正在上傳至 Google 雲端硬碟「{format_location(folder)} > {source.stem}」…")
        Thread(target=self.upload_worker,
               args=(source, formats, service, folder, destination), daemon=True).start()

    def upload_worker(self, source, formats, service, folder, destination):
        try:
            result = upload_recipe(source, formats, service=service, parent_id=folder["id"], **destination,
                                   progress=lambda text: self.events.put(("progress", text)))
            self.events.put(("uploaded", (result, folder)))
        except Exception as error:
            self.events.put(("error", f"雲端上傳失敗。本機 Markdown、圖片與已產生的文件均保留。\n{error}"))

    def show_upload_success(self, items, folder):
        recipe_folder = next((item for item in items if item.get("folder")), None)
        location = format_location(folder)
        if recipe_folder:
            location += " > " + recipe_folder["name"].split("／")[0]
        self.status.set(f"上傳成功！已上傳至「{location}」，本機原檔與轉檔均已保留。")
        names = "\n".join(f"• {item['name']}" for item in items if not item.get("folder"))
        if messagebox.askyesno("上傳成功",
                               f"已上傳到 Google 雲端硬碟：\n{location}\n\n{names}\n\n要在瀏覽器開啟這個資料夾嗎？",
                               parent=self.root):
            webbrowser.open(recipe_folder["url"] if recipe_folder
                            else f"https://drive.google.com/drive/folders/{folder['id']}")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                elif kind == "drive_ready":
                    self.drive_ready(*value)
                else:
                    self.set_busy(False)
                    if kind == "done":
                        self.result = Path(value).resolve()
                        self.status.set(f"轉換完成：{self.result.stem}，本機檔案位於 {self.result.parent}")
                        if self.pending_upload:
                            settings = self.pending_upload
                            self.pending_upload = None
                            self.after_conversion(value, **settings)
                    elif kind == "logged_in":
                        self.status.set("Claude 已登入，可以開始下載。")
                        messagebox.showinfo("Claude 已登入", "Claude 帳號已登入，之後會直接使用你的月租額度。")
                    elif kind == "uploaded":
                        self.show_upload_success(*value)
                    else:
                        self.status.set("處理失敗，請確認訊息後重試。")
                        messagebox.showerror("處理失敗", value)
        except Empty:
            pass
        self.root.after(150, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("處理中", "仍在處理檔案，請等候完成後關閉。")
            return
        self.root.destroy()


ASSETS = Path(__file__).resolve().parent.parent / "assets" / "icons"


def apply_icon(root):
    """視窗左上角與工作列使用 RecipeLens 圖示；找不到圖檔時沿用預設圖示。"""
    try:
        root._icon_image = tk.PhotoImage(master=root, file=str(ASSETS / "recipelens_256.png"))
        root.iconphoto(True, root._icon_image)
        if sys.platform == "win32":
            root.iconbitmap(default=str(ASSETS / "recipelens.ico"))
    except tk.TclError:
        pass


def format_location(folder):
    if not folder:
        return "尚未選擇（按「選擇…」指定）"
    return " > ".join(folder.get("path") or [folder["name"]])


def ask_upload(parent, source, drive_folder):
    """轉換成功對話窗。回傳 "upload"（上傳到預設位置）、"change"（先選資料夾）或 "no"。"""
    window = tk.Toplevel(parent)
    window.title("轉換成功")
    window.transient(parent)
    window.resizable(False, False)
    choice = {"value": "no"}

    def finish(value):
        choice["value"] = value
        window.destroy()

    body = ttk.Frame(window, padding=20)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=f"食譜「{source.stem}」已轉換完成，存放在本機：\n{source.parent}",
              wraplength=460).pack(anchor="w")
    if drive_folder:
        question = (f"是否上傳到 Google 雲端硬碟？\n\n存放位置：{format_location(drive_folder)} > {source.stem}"
                    "\n（自動建立食譜資料夾）")
    else:
        question = "是否上傳到 Google 雲端硬碟？\n\n尚未設定雲端存放位置，選「是」後請選擇資料夾。"
    ttk.Label(body, text=question, wraplength=460).pack(anchor="w", pady=(12, 16))
    buttons = ttk.Frame(body)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="否，只留在本機", command=lambda: finish("no")).pack(side="right")
    if drive_folder:
        ttk.Button(buttons, text="更換資料夾…", command=lambda: finish("change")).pack(side="right", padx=6)
        default = ttk.Button(buttons, text="是，上傳", command=lambda: finish("upload"))
    else:
        default = ttk.Button(buttons, text="是，選擇資料夾", command=lambda: finish("change"))
    default.pack(side="right")
    window.protocol("WM_DELETE_WINDOW", lambda: finish("no"))
    window.bind("<Escape>", lambda _: finish("no"))
    window.bind("<Return>", lambda _: default.invoke())
    default.focus_set()
    window.grab_set()
    window.wait_window()
    return choice["value"]


def main():
    if sys.platform == "win32":
        # 讓 Windows 工作列顯示 RecipeLens 圖示，而不是 Python 圖示
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RecipeLens.App")
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    RecipeLensApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

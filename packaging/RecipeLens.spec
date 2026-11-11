# PyInstaller 設定（資料夾版），由 packaging/build.ps1 呼叫，不建議直接執行。
# 產出 dist/RecipeLens/：RecipeLens.exe 與 _internal/；tools/ 由 build.ps1 另外放入。
from pathlib import Path
import re
import tomllib

from PyInstaller.utils.hooks import collect_all, collect_data_files

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
numbers = [int(part) for part in re.findall(r"\d+", version)[:3]]
numbers += [0] * (4 - len(numbers))

# exe 的版本資訊：檔案內容會顯示產品名稱、版本與發行者，程式碼簽章服務也要求這些欄位。
version_file = root / "build" / "version_info.txt"
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)},
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040404B0', [
      StringStruct('CompanyName', '3mofstudy'),
      StringStruct('FileDescription', 'RecipeLens 料理影片轉食譜'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'RecipeLens'),
      StringStruct('LegalCopyright', '© 3mofstudy'),
      StringStruct('OriginalFilename', 'RecipeLens.exe'),
      StringStruct('ProductName', 'RecipeLens'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0404, 1200])])
  ]
)
""", encoding="utf-8")

datas = [(str(root / "assets"), "assets"),
         (str(root / "src" / "picker_page.html"), "src")]
# Google 桌面 OAuth 用戶端：CI 由 Secret 寫入 data/；本機打包可沿用 config/ 內已匯入的檔案。
for client in (root / "data" / "google_client.json", root / "config" / "google_client.json"):
    if client.is_file():
        datas.append((str(client), "data"))
        break
else:
    print("警告：找不到 Google 用戶端 JSON，安裝版將無法上傳到 Google 雲端硬碟。")

# 錯誤回報接收端（Google Apps Script 網址與金鑰）；未提供時安裝版無法回報錯誤。
for endpoint in (root / "data" / "report_endpoint.json", root / "config" / "report_endpoint.json"):
    if endpoint.is_file():
        datas.append((str(endpoint), "data"))
        break
else:
    print("警告：找不到 report_endpoint.json，安裝版將無法回報錯誤。")

# googleapiclient 的離線 discovery 文件、Word 範本、PDF 字型資料。
for package in ("googleapiclient", "docx", "reportlab"):
    datas += collect_data_files(package)
binaries = []
hiddenimports = []
# 語音辨識的原生函式庫與模型設定。
for package in ("faster_whisper", "ctranslate2", "tokenizers"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis([str(root / "main.py")], pathex=[str(root)], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports,
             excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"])
# Qt 使用 Windows 內建 ICU；避免從開發工具 PATH 收進符號名稱不同的 ICU。
a.binaries = [entry for entry in a.binaries
              if not re.fullmatch(r"icu(uc|dt|in)\d*\.dll", Path(entry[0]).name.lower())]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="RecipeLens",
          console=False, upx=False, icon=str(root / "assets" / "icons" / "recipelens.ico"),
          version=str(version_file))
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="RecipeLens")

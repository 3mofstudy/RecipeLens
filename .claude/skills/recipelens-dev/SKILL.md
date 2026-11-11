---
name: recipelens-dev
description: 在 RecipeLens 專案撰寫、修改、重構或除錯 Python 程式時使用，包含新增功能、修 bug、調整 PySide6 介面、補測試與更新依賴。規範 rtk 指令前綴、模組分工、執行緒、測試與憑證處理。只驗證食譜產物或重現轉換失敗時改用 recipelens-validate。
---

# RecipeLens 寫程式注意事項

動手前先讀根目錄 `AGENTS.md` 與 `readme.md`，本技能是其補充；兩者衝突時以 `AGENTS.md` 為準。保留使用者既有設定與未提交的修改。回覆與文件用臺灣繁體中文。

## 1. Shell 指令一律經過 rtk

本專案以 rtk（Rust Token Killer）壓縮指令輸出、節省 token。在使用者的 Windows（PowerShell）環境執行任何 shell 指令時：

- 一般指令加 `rtk` 前綴，讓輸出經過過濾：
  - `rtk git status`、`rtk git diff`、`rtk git log -n 10`
  - `rtk ls src`、`rtk find . -name "*.py"`、`rtk grep "pattern" src`
  - `rtk read src/gui.py`（只需看檔案時；要精準行號或編輯前比對，改用內建 Read 工具）
- 需要完整原始輸出時用 `rtk proxy <指令>`：`uv` 安裝／執行、unittest 結果、打包腳本、錯誤 traceback、要逐行比對的輸出。
  - 安裝：`rtk proxy uv sync --locked --extra transcription`
  - 啟動 GUI：`rtk proxy uv run --locked --extra transcription python main.py`
  - 完整測試：`rtk proxy uv run --locked --extra transcription python -m unittest discover -s tests -p "test_*.py" -v`
  - 單一模組：`rtk proxy uv run --locked --extra transcription python -m unittest tests.test_gui -v`
- 懷疑壓縮後漏掉關鍵資訊（例如錯誤被摺疊），改用 `rtk proxy` 重跑一次，不要憑摘要下結論。
- 執行前若不確定 rtk 可用，先跑 `rtk --version` 與 `rtk gain`；`rtk gain` 不存在代表裝到同名的 Rust Type Kit。
- 若 shell 不在使用者 Windows 上（例如遠端 Linux VM）而 `rtk: command not found`，照常執行原指令並在回報中註明「此環境未使用 rtk」，不要自行安裝或改寫成別的工具。
- 內建 Read／Grep／Edit 工具不經過 shell，rtk 不作用；讀單一檔案用它們即可，大範圍搜尋或 git 指令才走 `rtk`。

## 2. 改程式前

- 先找出要改的模組，只讀相關檔案；依 `AGENTS.md` 的分工判斷放在哪裡：
  - 下載：`src/video_download.py`、`src/youtube_download.py`、`src/facebook_download.py`、`src/environment.py`
  - 字幕／語音／AI：`src/media.py`、`src/ai_recipe.py`、`src/recipe_lens.py`
  - 文件輸出：`src/recipe_export.py`、`src/document_export.py`、`src/local_storage.py`
  - 雲端：`src/cloud_upload.py`、`src/drive_browser.py`、`src/google_picker.py`、`src/qt_drive_dialog.py`
  - 介面：`src/gui.py`（流程協調）、`src/qt_window.py`（版面與預覽）、`src/qt_style.py`（樣式）
  - 設定與路徑：`src/settings.py`、`src/app_paths.py`；取消與復原：`src/cancellation.py`、`src/recovery.py`
- 核心處理不寫進 GUI；下載器、AI、輸出、上傳維持可獨立呼叫與測試的函數。
- 路徑一律用 `pathlib` 並經 `src/app_paths.py` 取得，需同時支援原始碼執行與 PyInstaller 安裝版（`_internal/`、`tools/`），不寫死使用者路徑。
- 檔案讀寫明確指定 `encoding="utf-8"`；Windows 預設編碼會讓中文亂碼。

## 3. 撰寫規則

- Python 版本以 `pyproject.toml` 為準（>=3.11,<3.14）；加型別註記，沿用既有命名與風格。
- 依賴只透過 uv 變更（`rtk proxy uv add <套件>`），同步提交 `uv.lock`；注意 `av<19` 等既有版本限制的註解原因。
- PySide6：耗時工作（網路、下載、語音辨識、AI、轉檔、上傳）放背景執行；只有主執行緒操作 widgets，透過 signals 或佇列回報。處理中鎖定重複啟動與本次設定。
- 進度只呈現實際階段，不捏造百分比；錯誤保留原文供查閱，重試要有上限。
- 外部程序（yt-dlp、ffmpeg、deno、Codex／Claude CLI）優先用專案或安裝版內附的路徑，以參數列表呼叫 `subprocess`，不用 `shell=True`；需支援取消。
- 食譜內容：來源沒有的用量、時間、溫度標示「影片未說明」或「待確認」，不在程式或 prompt 中誘導編造。
- 介面文字用臺灣繁體中文，維持藍白卡片、橘色主要按鈕與左設定右預覽的版面。

## 4. 測試

- 行為變更要補測試，放 `tests/test_*.py`，用 `unittest`。
- GUI 測試共用 `tests/qt_support.py` 的 QApplication（offscreen）；外部服務、AI、Google 一律模擬，不消耗額度、不建立真實雲端檔案。
- 先跑相關模組，完成前跑完整測試。回報時區分「離線／模擬測試通過」與「真實影片或雲端實測」，摘要 OK 但程序異常結束要查明原因。

## 5. 憑證與 Git

- 不讀出、輸出或提交 `config/google_client.json`、`config/google_token.json`、API key、token；只回報存在與否或格式。
- 不刪除或覆寫 `config/`、`output/`、`build/`、`dist/` 內使用者資料。
- 提交前用 `rtk git status` 與 `rtk git diff --stat` 檢查，確認沒有帶入憑證、`.venv/`、`output/`、`tools/`、打包產物。

## 6. 收尾

- 功能、設定、依賴或操作方式有變，同步更新 `readme.md`；新增 `.py` 檔要在 `readme.md` 補上對應說明。
- 簡短回報：改了哪些檔案、為什麼、跑了哪些測試與結果、尚未驗證的項目。

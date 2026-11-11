# RecipeLens 專案開發規則

本文件適用於本專案及其子目錄。修改前先閱讀相關程式與 `readme.md`，保留使用者既有設定與未提交的修改。

## 語言與溝通
- 回覆、說明、介面文字與開發文件使用臺灣繁體中文；程式識別字、套件名稱、指令及原始錯誤訊息可保留英文。
- 回報修改內容、驗證結果與未完成事項；清楚區分模擬測試及真實影片／雲端實測，不把嘗試執行當作成功。

## 環境與指令
- 使用 Python，版本範圍以 `pyproject.toml` 為準；使用 uv 管理環境與依賴，變更依賴時同步更新 `uv.lock`。
- Shell 指令一律加上 `rtk` 前綴；需要原始輸出時使用 `rtk proxy`。
- 安裝：`rtk proxy uv sync --locked --extra transcription`。
- 啟動 GUI：`rtk proxy uv run --locked --extra transcription python main.py`。
- 完整測試：`rtk proxy uv run --locked --extra transcription python -m unittest discover -s tests -p "test_*.py" -v`。

## 結構與責任分工
- 根目錄 `main.py` 是正式入口；應用程式放在 `src/`，測試放在 `tests/`，圖示與介面資源放在 `assets/`。
- Facebook、YouTube 下載器提供可重用函數；AI 判讀、文件輸出與雲端上傳各自獨立，勿將核心處理塞進 GUI。
- `src/gui.py` 協調流程，`src/qt_window.py` 建立介面與預覽，`src/qt_style.py` 管理樣式，`src/qt_drive_dialog.py` 處理雲端資料夾視窗。
- 功能、設定、依賴或操作方式改變時，同步更新根目錄 `readme.md`；開發文件以此檔為主要入口。

## 桌面介面
- 使用 PySide6；維持繁體中文、藍白卡片與橘色主要按鈕，以及左側設定、右側進度和食譜預覽的配置。
- 網路、影片下載、語音辨識、AI 與文件轉換放在背景執行；只有 Qt 主執行緒可操作 widgets，透過佇列或 signals 回報。
- 處理中防止重複啟動與變更本次設定；進度以實際階段呈現，不捏造百分比，失敗時保留可查閱的錯誤。
- 保留 Codex／Claude 切換、設定記憶、本機輸出選擇及雲端資料夾操作；預覽只載入本次食譜資料夾內的圖片。

## 食譜與輸出流程
- 使用者貼上網址後自動預選平台，再讓使用者確認；字幕由程式取得，不要求使用者上傳字幕檔。
- 保留平台字幕、內嵌字幕及無字幕三種模式；無字幕語音選項為國語、粵語、閩南語、其他。
- YouTube 資訊欄先檢查食材與做法，符合既有完整性規則時直接保留，避免多餘的 AI 判讀。
- 來源不足的食材用量、時間或溫度不得編造，標示「影片未說明」或「待確認」。
- 每次成功轉換都在本機保存 MD、PDF、DOCX 與步驟截圖；完成後顯示路徑，不跳出 Markdown 另存視窗。
- 沿用「平台-食譜名」及重名處理規則；雲端只上傳本次工作的所選格式，取消或失敗仍保留本機文件。
- Google 登入重用有效授權；上傳遵循目前設定的詢問／自動上傳流程及所選雲端位置。

## 工具與模型
- 優先使用 uv 專案環境的 yt-dlp，避免 PATH 上舊版遮蔽；明確傳入已安裝且相容的 JavaScript runtime。
- Codex「自動」會沿用 CLI 設定，不代表模型一定可用；依帳號及實測結果處理模型錯誤，重試必須有上限，不擅自修改全域 Codex 設定。
- 模型清單與外部服務能力可能變動，修改前核對官方文件或實際 CLI；勿將候選名稱宣稱為所有帳號都可用。

## 測試、憑證與版本控制
- 針對行為變更補充必要測試；GUI 測試共用 `tests/qt_support.py` 的 QApplication，使用 offscreen 與模擬外部服務。
- 真實下載、AI 與雲端上傳屬整合驗證，依使用者授權範圍執行；一般測試不應消耗 AI 額度或建立真實雲端檔案。
- 不輸出或提交 OAuth client secret、token、API key、SSH 私鑰或密碼；檢查憑證時只回報存在、格式或比對結果。
- `config/google_client.json` 為 App OAuth 設定，`config/google_token.json` 為使用者授權快取；勿任意刪除或覆寫。
- 保持 `.gitignore` 排除 `config/`、`data/` 中的憑證、`.venv/`、`output/`、`tools/` 及本機備份；提交前檢查差異與待提交檔案。

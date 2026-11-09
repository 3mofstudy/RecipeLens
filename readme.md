# RecipeLens

從 YouTube 或 Facebook 料理影片整理繁體中文食譜，輸出 Markdown 與關鍵步驟截圖。

## Windows 開發環境

1. 安裝 uv、FFmpeg，以及 Codex CLI 或 Claude Code CLI（擇一即可）。將包含 `ffmpeg.exe`、`ffprobe.exe` 的資料夾加入 Windows 使用者 PATH，並重新開啟 PowerShell。YouTube 擷取可能需要在 PATH 安裝 Deno。
2. 在專案目錄執行 `uv sync`，建立專案環境並安裝 yt-dlp。
3. 使用 Codex 時執行 `codex login` 登入，或用 `codex login status` 確認現有登入狀態。使用 Claude 時不需要 API 金鑰，也不需要開命令視窗：有 Pro 或 Max 月租即可。第一次用 Claude 轉換（或登入過期）時，RecipeLens 會在背景執行 `claude auth login`，自動開啟瀏覽器請你登入，登入後自動繼續；也可在「更多設定」按「登入 Claude 帳號」先登入。RecipeLens 呼叫 Claude 時會略過 `ANTHROPIC_API_KEY` 環境變數，確保使用月租額度而不是 API 計費；用量和 claude.ai 共用同一份額度。所有外部工具（FFmpeg、yt-dlp、Codex、Claude）都在背景執行，不會跳出黑色命令視窗。

## 執行

### GUI

```powershell
uv run --locked --extra transcription python main.py
```

貼上網址後，程式會預選 Facebook 或 YouTube，使用者確認後選擇字幕資訊，再按置中的「開始下載」。

字幕資訊預設為「應該有字幕檔，請程式自動檢查下載」。勾選「在 Markdown 保留完整字幕文字」時，只附上純字幕文字：自動移除時間軸、序號、格式標籤及語音轉錄的秒數標記，並略過自動字幕滾動重複的句子。

檔案名稱留空時，由 AI 判讀最合適的食譜名，以「平台-食譜名」命名，例如 Facebook 影片為 `FB-蔥爆豬肉`、YouTube 影片為 `YT-蔥爆豬肉`。輸出資料夾使用相同名稱，重名時加上 `-2`、`-3`。YouTube 資訊欄直接保留原文時不經 AI，改用影片標題整理出食譜名。

按「更多設定 ▼」展開進階選項。按「開始下載」時，這些選項會保存到 `config/settings.json`，成為下次開啟的預設值：

- AI 模型：第一層選 Codex 或 Claude，第二層選對應模型；清單沒有的模型可直接輸入。
- 本機輸出位置：預設為專案的 `output/`，可按「瀏覽…」改到其他資料夾。
- 下載轉換完成後，立即上傳至 Google 雲端硬碟。
- 上傳格式：預設全選 .md、PDF、DOCX。上傳 .md 時，`images/` 內的截圖會一併上傳到雲端的「檔名_images」資料夾，雲端 .md 的圖片連結指向該資料夾；本機原檔不變。
- 雲端存放位置：按「選擇…」挑選 Google 雲端硬碟資料夾，顯示為「我的雲端硬碟 > 09.我的食譜」。

- 沒有原始字幕檔，影片內有內嵌字幕。以語音轉錄和較密集的候選畫面協助 Codex 判讀。
- 沒有原始字幕檔，影片內無內嵌字幕。使用語音轉錄與候選畫面。
- 選擇「沒有原始字幕檔，影片內無內嵌字幕」時，可指定語音為國語、粵語、閩南語或其他。國語為預設值，其他會自動偵測語言。
- 應該有字幕檔。程式自行檢查並下載平台人工字幕，沒有人工字幕時嘗試平台自動字幕。無法取得時改用本機語音轉錄。GUI 不提供字幕檔上傳。

第三種模式才會啟用「保留完整字幕文字」。開啟後，Markdown 末尾會附上取得的全文，並標示人工字幕、自動字幕或本機語音轉錄的來源。關閉時仍使用字幕或轉錄文字整理食譜。

開始前可在主畫面輸入檔名，並勾選要上傳的 .md、PDF、DOCX（可全部選取）。按「確定，開始下載轉換」後，背景工作會回報進度。無論是否上傳，完成後自動將 MD、PDF、DOCX 與圖片保留在 output 資料夾，GUI 顯示可選取複製的 Markdown 完整路徑，不跳出另存視窗。

### 命令列

```powershell
uv run python main.py "https://www.facebook.com/reel/4545497162337751"
```

若影片沒有可用字幕但有音軌，啟用本機語音辨識。首次執行會下載 Whisper small 模型。

```powershell
uv run --extra transcription python main.py "https://www.facebook.com/reel/4545497162337751"
```

CLI 可用 `--provider Claude` 改用 Claude Code CLI 判讀，未指定時使用 Codex。如果 Codex 回報 `model_not_found`，用 `--model` 指定目前帳號可用的模型。本機範例使用 `gpt-5.6-sol`。

```powershell
uv run --locked --extra transcription python main.py --model gpt-5.6-sol "https://www.facebook.com/reel/4545497162337751"
```

每次成功執行會建立 `output/<平台-食譜名>/`，例如 `output/FB-蔥爆豬肉/`，內含同名的 `.md`、`.pdf`、`.docx` 和 `images/`。可用 `--output` 指定輸出根目錄、`--name "三杯雞"` 指定三份文件的共同檔名。搬移 Markdown 時請保留圖片資料夾。PDF／DOCX 會嵌入圖片。轉檔失敗時會顯示錯誤及已保留的 Markdown 所在位置。

## 處理流程

yt-dlp 取得可存取的影片與字幕，FFmpeg 擷取候選畫面。Codex CLI 會收到字幕或逐字稿和候選畫面，並回傳結構化的食材與步驟。Python 根據步驟時間擷取圖片，再產生 Markdown。未提供的用量標記為「影片未說明」。

Facebook Reel 的字幕可能直接嵌在畫面中。Codex 可從候選畫面讀取這些文字，並與語音轉錄和發布者的影片說明互相核對。內嵌字幕模式最多均勻抽取 60 張候選畫面，其餘模式最多 12 張，仍可能漏掉短暫出現的字幕。

## YouTube 資訊欄優先

下載前先讀取 YouTube 資訊欄，以程式規則檢查。須依序出現食材與做法標題、食材段落至少兩筆數字份量，以及做法段落至少兩個料理動作，才直接保留資訊欄原文。這條路徑不呼叫 Codex，也不做語音辨識。

規則無法證明食譜語意完整，少量食材的完整食譜可能轉入 AI 流程，描述不充分的資訊欄也可能誤判。直接保留原文時不翻譯語言，附上的六張圖片是影片參考畫面，尚未與步驟逐一配對。

## 模組

- `src/facebook_download.py` 提供 `download_facebook(url, work, tools, subtitles)`。
- `src/youtube_download.py` 提供 `download_youtube`、資訊欄讀取與食譜檢查。
- `src/video_download.py` 共用網址辨識和 yt-dlp 呼叫。
- `src/gui.py` 實作 Tkinter 視窗、問題選項與本機食譜路徑顯示。
- `src/ai_recipe.py` 專責 Codex／Claude 判讀和結構化食譜資料，並列出各平台可選模型。
- `src/settings.py` 讀寫「更多設定」的預設值。
- `src/media.py` 共用語音轉錄、截圖和外部工具執行。
- `src/recipe_export.py` 產出 AI 食譜 Markdown 與步驟圖片。
- `src/recipe_lens.py` 串接轉換流程，提供 `convert_video` 與原命令列入口。

CLI 可用 `--subtitle-mode embedded|none|original` 指定 GUI 對應的三種模式。原始字幕模式可搭配 `--subtitle-file "字幕.srt"`，及 `--keep-subtitles` 保留全文。舊指令預設保留 auto 模式，會優先使用可下載字幕。

語音語言也可透過 CLI 指定，例如 `--subtitle-mode none --speech-language 粵語`。CLI 未指定語言時維持自動偵測。

國語使用 Whisper small 模型及 zh 語言代碼，粵語使用 large-v3-turbo 及 yue。閩南語使用 large-v3-turbo 的中文解碼與台語語境提示，辨識結果需核對。首次選擇粵語或閩南語時會下載較大的模型，需要網路、磁碟空間與較多記憶體。

範例 Reel 已完成實片驗證。這支影片沒有可取得的字幕檔，使用 faster-whisper 轉錄後，由 Codex 產出「古早味肉燥」食譜及 8 張步驟截圖。

請使用你有權處理的影片。平台可能限制擷取公開影片，遇到連線或擷取錯誤時，腳本會顯示失敗原因。

## 專案目錄與入口

```text
RecipeLens/
├── main.py                  # 正式入口，無參數啟動 GUI，有網址參數啟動 CLI
├── tests/                   # 測試專用資料夾
│   ├── __init__.py
│   ├── test_environment.py  # 離線環境與流程測試
│   ├── test_cloud_upload.py # 轉檔及上傳重試測試
│   ├── test_google_picker.py # Google 官方選擇器與授權快取測試
│   ├── test_drive_browser.py # 雲端資料夾視窗測試
│   ├── test_gui.py          # 本機路徑顯示與 GUI 上傳流程測試
│   └── test_naming_and_ai.py # 平台-食譜名命名、Claude 解析、.md 連圖片上傳
├── src/                     # 應用程式模組
│   ├── __init__.py
│   ├── environment.py       # 尋找 FFmpeg、ffprobe、yt-dlp、Codex、Claude
│   ├── settings.py          # 更多設定的預設值
│   ├── cloud_upload.py      # Google Drive 登入及文件上傳
│   ├── drive_browser.py     # 類似檔案總管的雲端資料夾選擇視窗
│   ├── google_picker.py     # 舊版官方 Picker（GUI 已不使用）
│   ├── picker_server.py     # 本機安全回環服務
│   ├── picker_page.html     # Google 官方 Picker 的資料夾模式
│   ├── document_export.py   # Markdown 轉 PDF、DOCX
│   ├── local_storage.py     # 原子寫入本機紀錄
│   ├── gui.py
│   ├── facebook_download.py
│   ├── youtube_download.py
│   ├── video_download.py
│   ├── ai_recipe.py
│   ├── media.py
│   ├── recipe_export.py
│   └── recipe_lens.py
├── assets/icons/          # App 圖示：recipelens.svg（原始設計）、.ico、各尺寸 PNG
├── pyproject.toml
├── uv.lock
├── readme.md
└── output/
```

請在專案根目錄執行。src 內的模組使用套件相對匯入，統一從 main.py 啟動。

## 測試環境

```powershell
uv sync --locked --extra transcription
uv run --locked --extra transcription python -m unittest tests.test_environment -v
```

測試會檢查外部工具可用性、FFmpeg 和 ffprobe 可執行、PATH 尚未更新時的工具偵測，以及平台判讀。另使用模擬資料驗證 YouTube 資訊欄路徑不呼叫 AI、完整字幕附加與另存後圖片引用。這些測試不下載影片或消耗 Codex 額度。

Windows 程式可能保留啟動當時的 PATH。程式現在會額外讀取使用者 PATH，並檢查使用者目錄下 RecipeLens/ffmpeg 的既有安裝，因此從舊視窗啟動時仍可找到已安裝的工具。

## FFmpeg 專案內安裝

本機已將 FFmpeg 和 ffprobe 放在 tools/ffmpeg/bin/。程式優先使用這兩支執行檔，並可從入口所在專案位置找到它們，無須依賴啟動視窗繼承的 PATH。tools/ 是本機工具目錄，不納入版本控制。將專案移到其他電腦時，需另放入這兩支執行檔或安裝 FFmpeg 並加入 PATH。

修改程式後，請關閉先前的 RecipeLens 視窗，再從 main.py 重新啟動，讓新的程式碼生效。

已使用 YouTube 範例 hPCCwTdOZfk 完成自動字幕實測。程式自行取得 zh-HK 平台人工字幕，完成食譜、截圖及字幕全文匯出，過程無須使用者提供字幕檔。

## 本機保留與雲端上傳

GUI 轉換完成後，MD、PDF、DOCX 與截圖會固定保留在專案的 `output/recipe-<識別碼>/`。本機三種格式不受上傳格式勾選影響；上傳取消或失敗仍保留所有本機文件。CLI 預設使用相同的專案 output 目錄，可用 `--output` 指定其他位置。

主畫面的「本機保留與雲端上傳」區提供上傳格式複選、全部選取、檔名及可選的新雲端子資料夾名稱。檔名留空使用「食譜」，本機與雲端文件使用相同名稱。勾選「本次文件完成後上傳到 Google 雲端硬碟」才啟動上傳流程，預設關閉，格式預選 PDF。只上傳本次工作產生的文件，沒有獨立登入或選擇舊食譜上傳的按鈕。登入會在本次上傳需要時自動進行，沿用既有授權快取。開始處理時會保存本次選項，處理途中修改主畫面不影響本次工作。

PDF 與 Word 會嵌入食譜內的截圖，與 Markdown 儲存在同一個資料夾。依勾選格式上傳文件，Markdown 與圖片資料夾仍留在本機。.md 格式上傳完整原文，保留原本的本機圖片相對路徑；PDF／DOCX 會嵌入截圖。產生 PDF 使用 Windows 微軟正黑體，閱讀文件時無需另外尋找截圖檔。

### 首次設定 Google 登入

這個獨立 Python App 使用自己的 Google OAuth 登入，需先設定桌面應用程式用戶端。

1. 前往 Google Cloud Console，建立或選擇專案並啟用 Google Drive API 及 Google Picker API。
2. 設定 Google Auth Platform 的品牌資訊、目標對象及測試使用者。若應用程式處於測試模式，將要登入的 Google 帳號加入測試使用者。
3. 建立 OAuth 用戶端，應用程式類型選「桌面應用程式」，下載用戶端 JSON。
4. 開發者將下載的 JSON 配置到 `data/google_client.json`。程式會在首次使用時自動匯入到 `config/google_client.json`。一般使用者只需在主畫面勾選本次文件完成後上傳。
5. 第一次登入時，App 會開啟系統瀏覽器的 Google 授權畫面。完成後將授權保存到 `config/google_token.json`，後續登入重用有效憑證，過期時嘗試更新。

App 使用 `drive` 權限，以便 RecipeLens 自製的雲端資料夾視窗列出你全部的資料夾並上傳到其中。舊版使用 `drive.file`，第一次使用新版上傳時會自動重新開啟 Google 授權畫面，同意一次即可。若應用程式在 Google Auth Platform 仍處於測試模式，授權畫面會顯示「Google 尚未驗證這個應用程式」，按「繼續」即可；測試模式的授權約 7 天會過期，屆時重新登入。用戶端設定與登入憑證保存在專案的 `config/`，此資料夾已加入 .gitignore。

參考 [Google Drive Python 登入設定](https://developers.google.com/workspace/drive/api/quickstart/python) 與 [Drive 檔案上傳文件](https://developers.google.com/workspace/drive/api/guides/manage-uploads)。

### 獨立上傳模組

```powershell
uv run --locked --extra transcription python -m src.cloud_upload "output/recipe-識別碼/食譜.md" --format both
```

`--format` 接受 `md`、`pdf`、`docx`、`both`（PDF 和 DOCX）或 `all`（三種全部）。也可以用 `--formats md docx` 自訂複選組合。首次也可傳入 `--client-secrets "下載的用戶端.json"`。

轉檔及上傳紀錄保存在 Markdown 同層。未修改食譜和圖片時會重用已產生的文件，上傳則先記錄 Drive 檔案 ID，再傳送內容。獨立 CLI 可對同一份本機 Markdown 重試，沿用既有 ID 完成剩下的文件。保留這些紀錄可避免重試建立重複檔案。

### 雲端功能測試

```powershell
uv run --locked --extra transcription python -m unittest discover -s tests -p "test_*.py" -v
```

測試會實際產生包含中文與圖片的 PDF／DOCX，檢查本機 Markdown 保留、轉檔快取及上傳部分失敗後重試。Google Drive API 在測試中使用模擬物件，執行測試不會上傳檔案。真實登入與上傳需使用者完成 Google OAuth 設定後驗證。

## 雲端存放位置與命名

1. 在「更多設定」的「雲端存放位置」按「選擇…」，用資料夾視窗選好位置，例如「我的雲端硬碟 > 09.我的食譜」。這個根目錄會保存為預設值，下次沿用；每份食譜的資料夾都建在它底下。
2. 轉換成功後跳出「轉換成功」對話窗，顯示本機位置與雲端存放位置：
   - 「是，上傳」：在雲端存放位置（根目錄）下自動建立以食譜命名的資料夾，例如「我的雲端硬碟 > 09.我的食譜 > YT-蔥爆豬肉」，MD、PDF、DOCX 與 images 圖片資料夾都放在裡面，結構與本機相同。
   - 「更換資料夾…」：先開啟資料夾視窗改選位置（並記住新位置），再上傳。
   - 「否，只留在本機」：不上傳。
   尚未設定雲端存放位置時，按「是，選擇資料夾」會先開啟資料夾視窗。
3. 資料夾視窗類似檔案總管：上方有「上一層」「新增資料夾」「重新整理」圖示按鈕與目前位置；雙擊資料夾進入，Backspace 回上一層。選取資料夾後按「上傳到這裡」存入該資料夾，沒選取則存入目前位置。
4. 上傳完成後跳出「上傳成功」訊息，列出存放位置與檔案，可選擇在瀏覽器開啟該資料夾。
5. 取消資料夾視窗不會上傳；所有本機原檔、圖片及轉檔均保留。

「更多設定」勾選「下載轉換完成後，不再詢問」時，略過第 2 步，直接上傳到雲端存放位置。

以下 Google 官方 Picker 的說明為舊版流程，相關程式（`google_picker.py`、`picker_server.py`）仍保留但 GUI 已不使用。

目前使用 Google 官方 JavaScript Picker，透過 DocsView.setSelectFolderEnabled(true) 明確啟用資料夾選取，視窗底部會出現可確認的 Select 按鈕。先前使用 OAuth 內建桌面 Picker 的版本，在實際帳號中只會進入資料夾、沒有可確認目的地的按鈕，已改用這個實測可用的方式。

本機回環服務綁定 127.0.0.1 和隨機連接埠，使用不可預測的工作階段路徑，並檢查回傳請求來源。只有短期 access token 會交給 Google Picker，refresh token 保留在本機。服務停止後，瀏覽器分頁不再連線到本機；下一次上傳會建立新的工作階段。瀏覽器選定位置後，程式會透過 Drive API 驗證資料夾及寫入權限，並將 ID、名稱與網址儲存至 config/last_drive_folder.json。

本機已實測沿用既有桌面 OAuth 憑證與專案編號，成功顯示 Google 官方資料夾視窗，無需另行匯入憑證。有效的登入憑證繼續重用。

請在同一個 Google Cloud 專案啟用 [Google Picker API](https://console.cloud.google.com/apis/library/picker.googleapis.com)。官方介面參考 [資料夾選取設定](https://developers.google.com/workspace/drive/picker/reference/picker.docsview.setselectfolderenabled)。

CLI 可用 `--folder-id` 指定父資料夾、`--new-folder` 指定新資料夾名稱、`--name` 指定雲端檔名。CLI 依參數執行，GUI 使用 Google 瀏覽器選擇流程。上傳紀錄會區分雲端位置和檔名，改選不同的位置或名稱時視為另一份上傳。

自動測試涵蓋本機憑證重用、資料夾寫入權限驗證、實際本機 HTTP 回傳、跨來源請求拒絕、取消後不會上傳、Google 選定位置傳遞及本機資料保留。測試程式本身不會操作真實 Google 帳號或上傳檔案。本機 HTTP 回傳測試需允許回環網路連線。

## 實際上傳驗證

已獲使用者同意，以本機「蔥爆豬肉（5人份）」食譜完成 Google 官方資料夾選擇、返回 RecipeLens、三格式勾選、檔名設定及確認上傳。三份實際測試副本皆位於「09.我的食譜」，名稱為 RecipeLens上傳實測_食譜.md、RecipeLens上傳實測_食譜.pdf、RecipeLens上傳實測_食譜.docx，並核對非空白檔案大小及父資料夾。再次使用相同名稱重試會沿用既有檔案 ID。本機食譜、圖片、轉檔及驗證紀錄均保留。

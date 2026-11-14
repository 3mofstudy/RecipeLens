# 食影筆記（RecipeLens）開發者設定

一般開發規則見根目錄 `AGENTS.md`，使用說明見 `readme.md`。本文件記錄只需開發者設定一次的項目。

## 打包與發版

本機打包需要 uv 與 Inno Setup 6 或 7（<https://jrsoftware.org/isdl.php>）：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

腳本會安裝相依套件、下載 FFmpeg、yt-dlp、Deno 到 `build\`、執行單元測試、以 PyInstaller 資料夾版打包、檢查內附工具，最後以 Inno Setup 產生 `dist\installer\RecipeLens-Setup-<版本>.exe`。`-SkipTests` 略過測試，`-RefreshTools` 重新下載最新版工具。

GitHub Actions（`.github/workflows/windows-installer.yml`）在每次推送時打包並保留安裝程式作為 Artifact。發布新版時，先修改 `pyproject.toml` 的 `version`，再推送相同版本的標籤：

```powershell
git tag v0.2.0
git push origin v0.2.0
```

CI 會建立 GitHub Release，附上 `RecipeLens-Setup-0.2.0.exe` 與固定檔名的 `RecipeLens-Setup.exe`。CI 所需的 Google 用戶端放在 Actions Secret `GOOGLE_CLIENT_JSON`，錯誤回報設定放在 `REPORT_ENDPOINT_JSON`。安裝程式尚未進行程式碼簽章。

## Google OAuth 用戶端

RecipeLens 使用自己的 Google OAuth 桌面應用程式用戶端：

1. 在 Google Cloud Console 建立或選擇專案，啟用 Google Drive API。
2. 設定 Google Auth Platform 的品牌資訊、目標對象及測試使用者。應用程式處於測試模式時，要登入的帳號須加入測試使用者，授權約 7 天過期。
3. 建立 OAuth 用戶端，類型選「桌面應用程式」，下載用戶端 JSON。
4. 將 JSON 放到 `data/google_client.json`。程式首次使用時會匯入到 `config/google_client.json`；打包時依序取用這兩個位置並嵌入安裝版。
5. 使用者第一次上傳時會開啟 Google 授權畫面，授權保存到 `config/google_token.json`，之後重用並在過期時更新。

App 只使用 `https://www.googleapis.com/auth/drive.file` 權限（非敏感範圍），只能存取 App 自己建立的檔案與資料夾，因此不需經過 Google 受限範圍審查與 CASA 安全評估。所有食譜集中在「我的雲端硬碟」下的「食影筆記」根資料夾：資料夾帶有 `appProperties` 標記 `recipelensRoot=1`，ID 記在 `config/drive_app_root.json`；紀錄遺失時用標記找回，都找不到才新建。雲端資料夾視窗只瀏覽這個根資料夾以內。

在 Google Auth Platform 的「資料存取」只需加入 `drive.file`。要讓同意畫面不再顯示「Google 尚未驗證這個應用程式」並解除測試模式 7 天授權過期，將「目標對象」發布為正式版，並完成品牌驗證：應用程式名稱「食影筆記」、logo、首頁 `https://3mofstudy.app/recipelens/`、隱私權政策 `https://3mofstudy.app/recipelens/privacy.html`、授權網域 `3mofstudy.app`（須先在 Search Console 驗證）。網站原始檔放在 `3mofstudy/3mofstudy.github.io` repo。

`config/`、`data/` 內的憑證不進版本控制。

參考 [Google Drive Python 登入設定](https://developers.google.com/workspace/drive/api/quickstart/python) 與 [Drive 檔案上傳文件](https://developers.google.com/workspace/drive/api/guides/manage-uploads)。

## 錯誤回報接收端

錯誤報告以 HTTPS POST 送到開發者的 Google Apps Script 網頁應用程式，寫入 Google 試算表並可寄通知信；使用者不需設定寄信帳號，也不會看到開發者信箱。

1. 建立一份 Google 試算表，選「擴充功能 → Apps Script」，貼上 `docs/report_receiver.gs` 全部內容並儲存。
2. 「專案設定 → 指令碼屬性」新增 `REPORT_KEY`（一串隨機字串，例如 PowerShell 執行 `[guid]::NewGuid()`）；要收通知信再新增 `NOTIFY_EMAIL`。
3. 在編輯器執行一次 `testReceiver` 完成授權，試算表應出現「錯誤回報」分頁與一筆測試資料。
4. 「部署 → 新增部署作業 → 網頁應用程式」，執行身分選「我」，存取權選「所有人」，複製結尾為 `/exec` 的網址。修改程式碼後要「管理部署作業 → 編輯 → 新版本」，網址不變。
5. 建立 `data/report_endpoint.json`（打包時嵌入安裝版；原始碼執行也可放 `config/report_endpoint.json`），兩者都不進版本控制：

   ```json
   {"url": "https://script.google.com/macros/s/.../exec", "key": "與 REPORT_KEY 相同"}
   ```

   也可用環境變數 `RECIPELENS_REPORT_URL`、`RECIPELENS_REPORT_KEY` 覆蓋，方便測試。GitHub Actions 打包時，把同樣的 JSON 存成 Actions Secret `REPORT_ENDPOINT_JSON`。

金鑰會隨安裝版發佈，只能擋掉隨意的請求；接收端另有每 10 分鐘 30 筆的上限。若被濫用，在指令碼屬性更換 `REPORT_KEY` 並重新打包，即可讓舊版回報失效。

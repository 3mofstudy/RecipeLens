<#
打包 RecipeLens Windows 安裝程式。

在專案根目錄執行：
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1

需要：uv、Inno Setup 6 或 7（https://jrsoftware.org/isdl.php）。
FFmpeg、yt-dlp、Deno 與安裝程式的繁體中文語言檔會自動下載到 build\downloads\。
產出：dist\installer\RecipeLens-Setup-<版本>.exe

參數：
  -SkipTests     略過單元測試
  -RefreshTools  重新下載 FFmpeg、yt-dlp、Deno（取得最新版）
#>
param([switch]$SkipTests, [switch]$RefreshTools)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$downloads = Join-Path $root "build\downloads"
$tools = Join-Path $root "build\tools"
$app = Join-Path $root "dist\RecipeLens"
$installerDir = Join-Path $root "dist\installer"

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

function Invoke-Native {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File 執行失敗（代碼 $LASTEXITCODE）" }
}

function Get-Download($url, $name) {
    $target = Join-Path $downloads $name
    if ($RefreshTools -or -not (Test-Path $target)) {
        Write-Host "下載 $url"
        # Windows 內建的 curl.exe 比 Invoke-WebRequest 快很多，並顯示進度。
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & $curl.Source -L --fail --retry 3 --progress-bar -o "$target.part" $url
            if ($LASTEXITCODE -ne 0) { throw "下載失敗：$url" }
        } else {
            Invoke-WebRequest $url -OutFile "$target.part" -UseBasicParsing
        }
        Move-Item "$target.part" $target -Force
    }
    return $target
}

function Find-Iscc {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $bases = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA "Programs")) | Where-Object { $_ }
    foreach ($base in $bases) {
        $found = Get-ChildItem (Join-Path $base "Inno Setup*\ISCC.exe") -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($found) { return $found.FullName }
    }
    throw "找不到 Inno Setup。請從 https://jrsoftware.org/isdl.php 下載安裝後，重新開啟終端機。"
}

$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "RecipeLens $version"
$iscc = Find-Iscc
New-Item -ItemType Directory -Force $downloads, $tools | Out-Null

Step "安裝相依套件"
Invoke-Native uv @("sync", "--locked", "--extra", "transcription", "--group", "packaging")

Step "準備 FFmpeg、yt-dlp、Deno"
if ($RefreshTools -and (Test-Path $tools)) { Remove-Item $tools -Recurse -Force; New-Item -ItemType Directory $tools | Out-Null }
$ffmpegBin = Join-Path $tools "ffmpeg\bin"
$localFfmpeg = Join-Path $root "tools\ffmpeg\bin"
if (-not $RefreshTools -and -not (Test-Path (Join-Path $ffmpegBin "ffmpeg.exe")) -and
        (Test-Path (Join-Path $localFfmpeg "ffmpeg.exe")) -and (Test-Path (Join-Path $localFfmpeg "ffprobe.exe"))) {
    # 沿用專案 tools\ffmpeg 已安裝的 FFmpeg，省去下載。
    Write-Host "使用專案內的 FFmpeg：$localFfmpeg"
    New-Item -ItemType Directory -Force $ffmpegBin | Out-Null
    Copy-Item (Join-Path $localFfmpeg "ffmpeg.exe"), (Join-Path $localFfmpeg "ffprobe.exe") $ffmpegBin
}
if (-not (Test-Path (Join-Path $ffmpegBin "ffmpeg.exe"))) {
    $zip = Get-Download "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" "ffmpeg.zip"
    $extract = Join-Path $downloads "ffmpeg"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $zip $extract
    New-Item -ItemType Directory -Force $ffmpegBin | Out-Null
    foreach ($name in "ffmpeg.exe", "ffprobe.exe") {
        Get-ChildItem $extract -Recurse -Filter $name | Select-Object -First 1 | Copy-Item -Destination $ffmpegBin
    }
    Get-ChildItem $extract -Recurse -Filter "LICENSE*" | Select-Object -First 1 |
        Copy-Item -Destination (Join-Path $tools "ffmpeg\LICENSE.txt")
}
$ytdlp = Get-Download "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" "yt-dlp.exe"
Copy-Item $ytdlp (Join-Path $tools "yt-dlp.exe") -Force
if (-not (Test-Path (Join-Path $tools "deno.exe"))) {
    $zip = Get-Download "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" "deno.zip"
    Expand-Archive $zip $tools -Force
}
# 優先使用 Inno Setup 內附的繁體中文語言檔，舊版沒有時才下載。
$language = Join-Path (Split-Path $iscc) "Languages\ChineseTraditional.isl"
if (-not (Test-Path $language)) {
    $language = Get-Download "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseTraditional.isl" "ChineseTraditional.isl"
}

if (-not $SkipTests) {
    Step "執行單元測試"
    # 讓測試找得到剛準備好的 FFmpeg。
    $env:PATH = "$ffmpegBin;$tools;$env:PATH"
    Invoke-Native uv @("run", "--locked", "--extra", "transcription", "python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")
}

Step "PyInstaller 打包程式"
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
Invoke-Native uv @("run", "--locked", "--extra", "transcription", "--group", "packaging",
    "pyinstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build\pyinstaller",
    "packaging\RecipeLens.spec")
Copy-Item $tools (Join-Path $app "tools") -Recurse

Step "檢查打包內容"
Invoke-Native (Join-Path $app "tools\ffmpeg\bin\ffmpeg.exe") @("-hide_banner", "-version") | Select-Object -First 1
Invoke-Native (Join-Path $app "tools\ffmpeg\bin\ffprobe.exe") @("-hide_banner", "-version") | Select-Object -First 1
Write-Host ("yt-dlp " + (Invoke-Native (Join-Path $app "tools\yt-dlp.exe") @("--version")))
Invoke-Native (Join-Path $app "tools\deno.exe") @("--version") | Select-Object -First 1
foreach ($path in "RecipeLens.exe", "_internal\assets\icons\recipelens.ico", "_internal\src\picker_page.html") {
    if (-not (Test-Path (Join-Path $app $path))) { throw "打包內容缺少 $path" }
}
if (-not (Test-Path (Join-Path $app "_internal\data\google_client.json"))) {
    Write-Warning "未包含 Google 用戶端 JSON，安裝版無法上傳 Google 雲端硬碟。"
}

Step "Inno Setup 產生安裝程式"
Invoke-Native $iscc @("/Q", "/DAppVersion=$version", "/DSourceDir=$app", "/DOutputDir=$installerDir",
    "/DLanguageFile=$language", "packaging\RecipeLens.iss")
$setup = Join-Path $installerDir "RecipeLens-Setup-$version.exe"
if (-not (Test-Path $setup)) { throw "找不到安裝程式 $setup" }
if ($env:GITHUB_OUTPUT) {
    "installer=$setup" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
    "version=$version" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
}
Write-Host "`n完成：$setup" -ForegroundColor Green

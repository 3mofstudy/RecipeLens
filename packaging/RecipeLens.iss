; RecipeLens Windows 安裝程式（Inno Setup  7）。由 packaging\build.ps1 傳入版本與路徑。
; 預設安裝到使用者自己的 %LOCALAPPDATA%\Programs\RecipeLens，不需要系統管理員權限；
; 安裝時也可選擇「為所有使用者安裝」。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\RecipeLens"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif
#ifndef LanguageFile
  #define LanguageFile "compiler:Languages\ChineseTraditional.isl"
#endif

[Setup]
; AppId 固定不變，Windows 才會把新版視為同一個程式並直接升級。
AppId={{9196EBBB-F7E7-499E-B9EF-755DEA63A58B}
AppName=RecipeLens
AppVersion={#AppVersion}
AppVerName=RecipeLens {#AppVersion}
AppPublisher=3mofstudy
AppPublisherURL=https://3mofstudy.github.io/RecipeLens
AppSupportURL=https://github.com/3mofstudy/RecipeLens/issues
AppUpdatesURL=https://github.com/3mofstudy/RecipeLens/releases
AppCopyright=© 3mofstudy
VersionInfoVersion={#AppVersion}
VersionInfoProductName=RecipeLens
VersionInfoDescription=RecipeLens 安裝程式
DefaultDirName={autopf}\RecipeLens
DefaultGroupName=RecipeLens
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=RecipeLens-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\recipelens.ico
UninstallDisplayIcon={app}\RecipeLens.exe
UninstallDisplayName=RecipeLens
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; 升級時自動關閉正在執行的 RecipeLens。
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "zh_TW"; MessagesFile: "{#LanguageFile}"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; 升級前清除舊版的程式套件與工具，避免新舊檔案混用。使用者設定與食譜不在這裡，不受影響。
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\tools"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\RecipeLens"; Filename: "{app}\RecipeLens.exe"; AppUserModelID: "RecipeLens.App"
Name: "{autodesktop}\RecipeLens"; Filename: "{app}\RecipeLens.exe"; AppUserModelID: "RecipeLens.App"; Tasks: desktopicon

[Run]
Filename: "{app}\RecipeLens.exe"; Description: "{cm:LaunchProgram,RecipeLens}"; Flags: nowait postinstall skipifsilent

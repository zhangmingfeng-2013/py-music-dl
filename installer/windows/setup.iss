; =============================================================================
; 音乐下载器 —— Windows 安装向导（Inno Setup 6）
; 由 build_windows.ps1 传入版本号：/DAPP_VERSION=x.y.z
; =============================================================================
#ifndef APP_VERSION
  #define APP_VERSION "0.0.0"
#endif

[Setup]
AppId={{8F3A7C21-6E94-4D2B-9A57-202510021640}
AppName=音乐下载器
AppVersion={#APP_VERSION}
AppVerName=音乐下载器 {#APP_VERSION}
AppPublisher=MusicDownloader
AppPublisherURL=https://example.com/music-downloader
AppSupportURL=https://example.com/music-downloader
DefaultDirName={autopf}\MusicDownloader
DefaultGroupName=音乐下载器
DisableProgramGroupPage=yes
LicenseFile=..\..\installer\windows\license.txt
OutputDir=..\..\dist
OutputBaseFilename=MusicDownloader-{#APP_VERSION}-windows-x64-setup
SetupIconFile=..\..\assets\icons\app.ico
UninstallDisplayIcon={app}\MusicDownloader.exe
UninstallDisplayName=音乐下载器 {#APP_VERSION}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; 向导侧边大图（可选，缺失不影响构建）
; WizardImageFile=..\..\assets\icons\icon_512.png

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\..\dist\MusicDownloader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\音乐下载器"; Filename: "{app}\MusicDownloader.exe"; IconFilename: "{app}\MusicDownloader.exe"
Name: "{group}\卸载音乐下载器"; Filename: "{uninstallexe}"
Name: "{autodesktop}\音乐下载器"; Filename: "{app}\MusicDownloader.exe"; IconFilename: "{app}\MusicDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MusicDownloader.exe"; Description: "立即启动音乐下载器"; Flags: nowait postinstall skipifsilent

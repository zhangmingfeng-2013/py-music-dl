; =============================================================================
; 拾音 —— Windows 安装向导（Inno Setup 6）
; 由 build_windows.ps1 传入版本号：/DAPP_VERSION=x.y.z
; =============================================================================
#ifndef APP_VERSION
  #define APP_VERSION "0.0.0"
#endif

[Setup]
AppId={{E270ADF3-BDE9-441B-A002-9967AAA4EBEA}
AppName=拾音
AppVersion={#APP_VERSION}
AppVerName=拾音 {#APP_VERSION}
AppPublisher=Shiyin
DefaultDirName={autopf}\Shiyin
DefaultGroupName=拾音
DisableProgramGroupPage=yes
LicenseFile=..\..\installer\windows\license.txt
OutputDir=..\..\dist
OutputBaseFilename=Shiyin-{#APP_VERSION}-windows-x64-setup
SetupIconFile=..\..\assets\icons\app.ico
UninstallDisplayIcon={app}\Shiyin.exe
UninstallDisplayName=拾音 {#APP_VERSION}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\..\dist\Shiyin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\拾音"; Filename: "{app}\Shiyin.exe"; IconFilename: "{app}\Shiyin.exe"
Name: "{group}\卸载拾音"; Filename: "{uninstallexe}"
Name: "{autodesktop}\拾音"; Filename: "{app}\Shiyin.exe"; IconFilename: "{app}\Shiyin.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Shiyin.exe"; Description: "立即启动拾音"; Flags: nowait postinstall skipifsilent

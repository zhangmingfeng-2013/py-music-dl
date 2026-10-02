# =============================================================================
# 音乐下载器 —— Windows 安装包构建脚本（PowerShell，在 Windows 上执行）
#
# 产物：dist\MusicDownloader-<version>-windows-x64-setup.exe
# 前置：Python 3.10+（含 pip）、Inno Setup 6（默认安装路径自动探测；
#       也可用 choco install innosetup 安装）
#
# 可选：将 ffmpeg.exe 放到 installer\bin\ffmpeg.exe，会自动随包打入；
#       否则音频转码功能依赖系统 PATH 中的 ffmpeg。
# =============================================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

$Version = (Get-Content "installer\VERSION" -Raw).Trim()
Write-Host "版本: $Version"

Write-Host "==> [1/4] 安装构建依赖（Pillow / PyInstaller）"
python -m pip install --disable-pip-version-check pillow pyinstaller | Out-Null

Write-Host "==> [2/4] 生成图标资源（PNG/ICO）"
$env:QT_QPA_PLATFORM = "offscreen"
python assets\icons\gen_icons.py

Write-Host "==> [3/4] PyInstaller 冻结"
python -m PyInstaller music-dl.spec --noconfirm
if (-not (Test-Path "dist\MusicDownloader\MusicDownloader.exe")) {
    throw "未找到 dist\MusicDownloader\MusicDownloader.exe"
}

Write-Host "==> [4/4] Inno Setup 编译安装向导"
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Iscc = $cmd.Source }
}
if (-not $Iscc) { throw "未找到 ISCC.exe，请先安装 Inno Setup 6" }

& $Iscc "/DAPP_VERSION=$Version" "installer\windows\setup.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }

Write-Host ""
Write-Host "完成：$Root\dist\MusicDownloader-$Version-windows-x64-setup.exe"

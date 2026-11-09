# 打包成便携版（免安装、解压即用）
# 用法:  powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist\ToCheckNext"
$pyVer = "3.12.14"
$pyZip = "python-$pyVer-embed-amd64.zip"
$pyUrl = "https://www.python.org/ftp/python/$pyVer/$pyZip"
$py = "C:\Users\edwar\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

Write-Host "==> 准备目录 $dist"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $dist | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dist "runtime") | Out-Null

Write-Host "==> 下载 Python 嵌入式运行时"
$tmp = Join-Path $env:TEMP $pyZip
if (-not (Test-Path $tmp)) {
    curl.exe -sSL -o $tmp $pyUrl
}
Expand-Archive -LiteralPath $tmp -DestinationPath (Join-Path $dist "runtime") -Force

$pth = Get-ChildItem (Join-Path $dist "runtime") -Filter "python*._pth" | Select-Object -First 1
if ($pth) {
    $content = Get-Content $pth.FullName
    $content = $content | ForEach-Object { if ($_ -eq "#import site") { "import site" } else { $_ } }
    if ($content -notcontains "Lib\site-packages") { $content += "Lib\site-packages" }
    Set-Content -LiteralPath $pth.FullName -Value $content -Encoding ASCII
}

Write-Host "==> 安装依赖到便携运行时"
& $py -m pip install --disable-pip-version-check --no-input --target (Join-Path $dist "runtime\Lib\site-packages") `
    python-docx python-pptx openpyxl Pillow pypdf 2>&1 | Select-Object -Last 3

Write-Host "==> 复制程序文件"
Copy-Item (Join-Path $root "run.py") $dist
Copy-Item (Join-Path $root "run_check.py") $dist
Copy-Item (Join-Path $root "app") (Join-Path $dist "app") -Recurse
New-Item -ItemType Directory -Path (Join-Path $dist "data") -Force | Out-Null

$bat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" "%~dp0runtime\pythonw.exe" "%~dp0run.py" --port 8765
"@
Set-Content -LiteralPath (Join-Path $dist "启动 ToCheck Next.bat") -Value $bat -Encoding Default

$bat2 = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python.exe" "%~dp0run.py" --port 8765
pause
"@
Set-Content -LiteralPath (Join-Path $dist "启动（控制台）.bat") -Value $bat2 -Encoding Default

$readme = @"
ToCheck Next 便携版
====================
1. 解压到任意目录（路径不要含特殊字符）
2. 双击「启动 ToCheck Next.bat」
3. 浏览器会自动打开 http://127.0.0.1:8765

数据都在本目录 data\ 下：
  data\reports  查重历史（.meta.json / .json.gz / .txt）
  data\images   相似图片缩略图
  logs\         每次任务的运行日志

不需要安装 Python，不会写注册表。
"@
Set-Content -LiteralPath (Join-Path $dist "使用说明.txt") -Value $readme -Encoding UTF8

Write-Host "==> 压缩"
$zip = Join-Path $root "dist\ToCheckNext-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip

Write-Host ""
Write-Host "完成: $zip"
Write-Host ("大小: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))

param(
  [Parameter(Mandatory = $true)][string]$Dir,
  [string]$OutFile = "",
  [string]$Lang = "zh-Hans-CN",
  [int]$TimeoutSec = 300
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if (-not $OutFile) { $OutFile = Join-Path $Dir "ocr.json" }

function Write-Result($obj, $code) {
  $json = $obj | ConvertTo-Json -Depth 6 -Compress
  [System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))
  exit $code
}

try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
      $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

  function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    if (-not $netTask.Wait([Math]::Max(1, $TimeoutSec) * 1000)) { throw "timeout" }
    $netTask.Result
  }

  [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

  $engine = $null
  foreach ($tag in @($Lang, "zh-Hans-CN", "zh-Hans", "en-US")) {
    if (-not $tag) { continue }
    try {
      $language = New-Object Windows.Globalization.Language $tag
      $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
      if ($engine) { break }
    } catch { }
  }
  if (-not $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  }
  if (-not $engine) { Write-Result @{ ok = $false; error = "no_ocr_engine" } 3 }

  $pages = @()
  foreach ($f in (Get-ChildItem -LiteralPath $Dir -Filter *.png | Sort-Object Name)) {
    try {
      $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
      $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
      try {
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        $lines = @()
        foreach ($line in $res.Lines) { $lines += $line.Text }
        $pages += @{ file = $f.Name; lines = $lines; ok = $true }
      } finally {
        $stream.Dispose()
      }
    } catch {
      $pages += @{ file = $f.Name; lines = @(); ok = $false; error = "$($_.Exception.Message)" }
    }
  }

  $tagName = ""
  try { $tagName = $engine.RecognizerLanguage.LanguageTag } catch { }
  Write-Result @{ ok = $true; lang = $tagName; pages = $pages } 0
} catch {
  Write-Result @{ ok = $false; error = "$($_.Exception.Message)"; trace = "$($_.ScriptStackTrace)" } 4
}

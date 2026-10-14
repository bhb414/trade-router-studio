param(
  [string]$RouterSource = "",
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $RouterSource) {
  $RouterSource = Join-Path (Split-Path -Parent $ProjectRoot) "trade-router"
}
if (-not $Python) {
  $LocalPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  $Python = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
}
$RouterSource = (Resolve-Path $RouterSource).Path
$Version = & $Python -c "import sys; sys.path.insert(0, r'$ProjectRoot\src'); from trade_router_studio.version import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw "버전을 읽지 못했습니다." }

Push-Location $ProjectRoot
try {
  & $Python -m pip install --disable-pip-version-check $RouterSource
  if ($LASTEXITCODE -ne 0) { throw "Trade Router 설치에 실패했습니다." }
  & $Python -m pip install --disable-pip-version-check ".[build]"
  if ($LASTEXITCODE -ne 0) { throw "Studio 빌드 의존성 설치에 실패했습니다." }

  Remove-Item -Recurse -Force ".release-build", ".release-dist", "release" -ErrorAction SilentlyContinue
  & $Python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name TradeRouterStudio `
    --distpath ".release-dist" --workpath ".release-build\main" `
    --specpath ".release-build" `
    --collect-all trade_router --collect-all trade_router_studio `
    "src\trade_router_studio\desktop.py"
  if ($LASTEXITCODE -ne 0) { throw "Studio 실행 파일 빌드에 실패했습니다." }

  & $Python -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name TradeRouterUpdater `
    --distpath ".release-dist\updater" --workpath ".release-build\updater" `
    --specpath ".release-build" `
    "src\trade_router_studio\updater.py"
  if ($LASTEXITCODE -ne 0) { throw "Updater 실행 파일 빌드에 실패했습니다." }

  $Bundle = Join-Path $ProjectRoot ".release-dist\TradeRouterStudio"
  Copy-Item ".release-dist\updater\TradeRouterUpdater.exe" $Bundle
  Copy-Item "README.md", "LICENSE" $Bundle
  [System.IO.File]::WriteAllText((Join-Path $Bundle "VERSION"), $Version, [System.Text.UTF8Encoding]::new($false))

  New-Item -ItemType Directory -Force "release" | Out-Null
  $Archive = Join-Path $ProjectRoot "release\TradeRouterStudio-windows-x64.zip"
  Compress-Archive -Path "$Bundle\*" -DestinationPath $Archive -CompressionLevel Optimal
  $Hash = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
  [System.IO.File]::WriteAllText("$Archive.sha256", "$Hash  TradeRouterStudio-windows-x64.zip`n", [System.Text.UTF8Encoding]::new($false))
  Write-Host "Built Trade Router Studio v$Version"
  Write-Host $Archive
  Write-Host "SHA256 $Hash"
}
finally {
  Pop-Location
}

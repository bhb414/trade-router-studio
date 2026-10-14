param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^\d+\.\d+\.\d+$')]
  [string]$Version
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $ProjectRoot
try {
  if (git status --porcelain) {
    throw "변경 파일을 먼저 커밋하거나 되돌리세요."
  }
  $Tag = "v$Version"
  if (git tag --list $Tag) {
    throw "$Tag 태그가 이미 있습니다."
  }
  $Pyproject = [System.IO.File]::ReadAllText((Join-Path $ProjectRoot "pyproject.toml"))
  $Pyproject = [regex]::Replace(
    $Pyproject,
    '(?m)^version = "[^"]+"(?=\r?$)',
    "version = `"$Version`"",
    1
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $ProjectRoot "pyproject.toml"),
    $Pyproject,
    [System.Text.UTF8Encoding]::new($false)
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $ProjectRoot "src\trade_router_studio\version.py"),
    "__version__ = `"$Version`"`n",
    [System.Text.UTF8Encoding]::new($false)
  )

  $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path $Python)) { $Python = "python" }
  & $Python -m ruff check .
  if ($LASTEXITCODE -ne 0) { throw "Ruff 검사에 실패했습니다." }
  & $Python -m pytest -q
  if ($LASTEXITCODE -ne 0) { throw "테스트에 실패했습니다." }

  git add pyproject.toml src/trade_router_studio/version.py
  git commit -m "Release $Tag"
  if ($LASTEXITCODE -ne 0) { throw "릴리스 커밋에 실패했습니다." }
  git tag -a $Tag -m "Trade Router Studio $Tag"
  if ($LASTEXITCODE -ne 0) { throw "릴리스 태그 생성에 실패했습니다." }
  git push origin main
  if ($LASTEXITCODE -ne 0) { throw "main 푸시에 실패했습니다." }
  git push origin $Tag
  if ($LASTEXITCODE -ne 0) { throw "$Tag 푸시에 실패했습니다." }
  Write-Host "$Tag 배포 빌드를 시작했습니다. GitHub Actions와 Releases를 확인하세요."
}
finally {
  Pop-Location
}

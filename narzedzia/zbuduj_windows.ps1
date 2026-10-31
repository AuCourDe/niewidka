<#
Build Niewidka for Windows: clone from GitHub -> venv (py -3.13)
-> PyInstaller onedir without a console -> ZIP package. Model weights are NOT in the package:
the program downloads them after installation (first run or Settings). The Inno Setup
installer is built only when iscc is on PATH (Inno is not installed unnecessarily).
Run ON WINDOWS (or from WSL through powershell.exe):

  powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1

-Rpo points to an existing repository (CI: the workflow already has a checkout) and skips the clone.
Output:
  <KatalogBudowy>\dist\Niewidka\Niewidka.exe
  <KatalogBudowy>\Niewidka-<version>-windows-x64.zip
#>
param(
  [string]$KatalogBudowy = (Join-Path $env:USERPROFILE "niewidka-build"),
  [string]$RepoUrl = "https://github.com/AuCourDe/niewidka.git",
  [string]$Rpo = "",
  [string]$Python = "py -3.13",
  [switch]$PominTesty
)
$ErrorActionPreference = "Stop"
# the working directory must be local to Windows: with a cwd on \\wsl.localhost PyInstaller
# would add the WSL working tree to the module search paths
New-Item -ItemType Directory -Force -Path $KatalogBudowy | Out-Null
Set-Location $KatalogBudowy

# a running Niewidka holds DLLs in dist: PyInstaller --clean would get Access Denied
if (Get-Process Niewidka -ErrorAction SilentlyContinue) {
  throw "Niewidka jest uruchomiona: zamknij ja przed budowa (blokuje dist\Niewidka)"
}

if ($Rpo -ne "") {
  $Repo = $Rpo
  Write-Host "== 1. Repozytorium: używam istniejącego $Repo =="
} else {
  $Repo = Join-Path $KatalogBudowy "repo"
  Write-Host "== 1. Repozytorium (klon z GitHuba, nie kopia katalogu roboczego) =="
  if (Test-Path (Join-Path $Repo ".git")) {
    git -C $Repo pull --ff-only
  } else {
    git clone $RepoUrl $Repo
  }
}
$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
Write-Host ("  commit: " + (git -C $Repo rev-parse --short HEAD))

Write-Host "== 2. Srodowisko wirtualne (Python 3.13) i zaleznosci =="
Invoke-Expression "$Python -m venv $Repo\.venv"
& $VenvPython -m pip install --upgrade pip
# dependencies ONLY from a lockfile with hashes: the same versions as the
# release workflow; a version change = a deliberate decision in wymagania-budowy.in
& $VenvPython -m pip install --require-hashes -r "$Repo\narzedzia\wymagania-budowy.txt"
& $VenvPython -c "import webview, onnxruntime, keyring; print('importy OK')"

if (-not $PominTesty) {
  Write-Host "== 3. Testy jednostkowe na Windows (bez wag: testy modelowe same skacza) =="
  Push-Location $Repo
  & $VenvPython -m pytest tests/ -q
  if ($LASTEXITCODE -ne 0) { Pop-Location; throw "testy jednostkowe nie przeszly" }
  Pop-Location
}

Write-Host "== 4. Ikona =="
# the proper icon (the cap mark) is in the repo (niewidka\web\ikona.ico); the generator
# narzedzia\ikona.py is only a fallback pattern in case the repo file is missing
$IkonaRepo = Join-Path $Repo "niewidka\web\ikona.ico"
if (Test-Path $IkonaRepo) {
  Copy-Item $IkonaRepo (Join-Path $KatalogBudowy "ikona.ico") -Force
} else {
  & $VenvPython (Join-Path $Repo "narzedzia\ikona.py") --wyjscie (Join-Path $KatalogBudowy "ikona.ico")
}

Write-Host "== 5. Plik wersji =="
$Dopasowanie = Select-String -Path (Join-Path $Repo "pyproject.toml") -Pattern '^version = "([^"]+)"'
$Wersja = $Dopasowanie.Matches[0].Groups[1].Value
$Czesci = $Wersja.Split(".")
while ($Czesci.Count -lt 4) { $Czesci += "0" }
@"
# -*- coding: UTF-8 -*-
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($Czesci[0]), $($Czesci[1]), $($Czesci[2]), $($Czesci[3])),
    prodvers=($($Czesci[0]), $($Czesci[1]), $($Czesci[2]), $($Czesci[3])),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable("041504b0", [
      StringStruct("CompanyName", "Niewidka"),
      StringStruct("FileDescription", "Niewidka - lokalne ukrywanie danych osobowych"),
      StringStruct("FileVersion", "$Wersja"),
      StringStruct("ProductName", "Niewidka"),
      StringStruct("ProductVersion", "$Wersja")])]),
    VarFileInfo([VarStruct("Translation", [1045, 1200])])])
"@ | Out-File -Encoding ascii (Join-Path $KatalogBudowy "wersja.txt")
# validate BEFORE PyInstaller: the loader prints the full exception chain on error
& $VenvPython -c "from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file; load_version_info_from_text_file(r'$KatalogBudowy\wersja.txt'); print('wersja OK')"

Write-Host "== 6. PyInstaller (onedir, bez konsoli) =="
$StartPy = Join-Path $KatalogBudowy "start.py"
Set-Content -Path $StartPy -Encoding ascii -Value "import sys`r`nfrom niewidka.okno import uruchom`r`nsys.exit(uruchom())"
& $VenvPython -m PyInstaller `
  --noconfirm --clean --windowed --name Niewidka `
  --icon (Join-Path $KatalogBudowy "ikona.ico") `
  --version-file (Join-Path $KatalogBudowy "wersja.txt") `
  --paths $Repo `
  --distpath (Join-Path $KatalogBudowy "dist") `
  --workpath (Join-Path $KatalogBudowy "praca") `
  --specpath $KatalogBudowy `
  --collect-all webview `
  --add-data ("{0};niewidka\web" -f (Join-Path $Repo "niewidka\web")) `
  --add-data ("{0};niewidka\dane" -f (Join-Path $Repo "niewidka\dane")) `
  --hidden-import keyring.backends.Windows `
  --copy-metadata keyring `
  --hidden-import uvicorn.loops.auto --hidden-import uvicorn.loops.asyncio `
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.http.h11_impl `
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on `
  $StartPy
if ($LASTEXITCODE -ne 0) { throw "PyInstaller nie powiodl sie" }

Write-Host "== 7. Paczka ZIP (onedir, bez wag: modele pobiera program po instalacji) =="
$Zip = Join-Path $KatalogBudowy "Niewidka-$Wersja-windows-x64.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path (Join-Path $KatalogBudowy "dist\Niewidka") -DestinationPath $Zip
$Rozmiar = "{0:N0} MB" -f ((Get-Item $Zip).Length / 1MB)
Write-Host "  $Zip ($Rozmiar)"

Write-Host "== 8. Instalator Inno Setup (tylko gdy iscc jest) =="
$Iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($Iscc) {
  $Iss = Join-Path $KatalogBudowy "niewidka.iss"
  @"
[Setup]
AppName=Niewidka
AppVersion=$Wersja
AppVerName=Niewidka $Wersja
DefaultDirName={autopf}\Niewidka
DefaultGroupName=Niewidka
OutputDir=$KatalogBudowy\instalator
OutputBaseFilename=Niewidka-$Wersja-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Niewidka.exe

[Files]
Source: "$KatalogBudowy\dist\Niewidka\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Niewidka"; Filename: "{app}\Niewidka.exe"
"@ | Out-File -Encoding ascii $Iss
  & iscc $Iss
} else {
  Write-Host "  Inno Setup (iscc) niedostepny: zostawiam paczke ZIP; instalator .exe jako krok do zrobienia."
}

Write-Host "== Gotowe: dist\Niewidka\Niewidka.exe + $Zip =="

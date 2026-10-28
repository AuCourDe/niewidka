<#
Budowa Niewidki dla Windows (K6): klon z GitHuba -> venv (py -3.13) -> PyInstaller
onedir bez konsoli -> wagi bardsai z weryfikacją SHA-256 wg manifest.json -> paczka
ZIP. Instalator Inno Setup buduje się tylko, gdy iscc jest w PATH (bez instalowania
Inno bez potrzeby). Uruchomienie NA WINDOWS (albo z WSL przez powershell.exe):

  powershell -ExecutionPolicy Bypass -File narzedzia\zbuduj_windows.ps1 [-Wagi <katalog>]

Domyślne źródło wag: \\wsl.localhost\Ubuntu-24.04\mnt\projekty\models\niewidka (tylko
pliki wymienione w manifest.json; lfm25 pomijany; uwaga: ~/models to dowiązanie
do /mnt/projekty/models, którego \\wsl.localhost nie prowadzi). Wynik:
  <KatalogBudowy>\dist\Niewidka\Niewidka.exe   (wagi w dist\Niewidka\modele)
  <KatalogBudowy>\Niewidka-<wersja>-windows-x64.zip
#>
param(
  [string]$KatalogBudowy = "C:\Users\uzytkownik\niewidka-build",
  [string]$RepoUrl = "https://github.com/AuCourDe/niewidka.git",
  [string]$Wagi = "\\wsl.localhost\Ubuntu-24.04\mnt\projekty\models\niewidka",
  [string]$Python = "py -3.13",
  [switch]$PominTesty
)
$ErrorActionPreference = "Stop"
# katalog roboczy musi byc lokalny dla Windows: z cwd na \\wsl.localhost PyInstaller
# wlaczylby drzewo robocze WSL w sciezki przeszukiwania modulow
Set-Location $KatalogBudowy

$Repo = Join-Path $KatalogBudowy "repo"
$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Host "== 1. Repozytorium (klon z GitHuba, nie kopia katalogu roboczego) =="
if (Test-Path (Join-Path $Repo ".git")) {
  git -C $Repo pull --ff-only
} else {
  git clone $RepoUrl $Repo
}
Write-Host ("  commit: " + (git -C $Repo rev-parse --short HEAD))

Write-Host "== 2. Srodowisko wirtualne (Python 3.13) i zaleznosci =="
Invoke-Expression "$Python -m venv $Repo\.venv"
& $VenvPython -m pip install --upgrade pip
# zaleznosci runtime = [project].dependencies z pyproject.toml + desktop/budowa
& $VenvPython -m pip install fastapi uvicorn cryptography keyring onnxruntime python-docx `
  python-multipart python-stdnum tokenizers httpx pywebview pythonnet pyinstaller pytest scipy
& $VenvPython -c "import webview, onnxruntime, keyring; print('importy OK')"

if (-not $PominTesty) {
  Write-Host "== 3. Testy jednostkowe na Windows (bez wag: testy modelowe same skacza) =="
  Push-Location $Repo
  & $VenvPython -m pytest tests/ -q
  if ($LASTEXITCODE -ne 0) { Pop-Location; throw "testy jednostkowe nie przeszly" }
  Pop-Location
}

Write-Host "== 4. Ikona =="
& $VenvPython (Join-Path $Repo "narzedzia\ikona.py") --wyjscie (Join-Path $KatalogBudowy "ikona.ico")

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
# walidacja PRZED PyInstallerem: loader wypisuje pelny lancuch wyjatkow przy bledzie
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
  --collect-all pywebview `
  --hidden-import keyring.backends.Windows `
  --copy-metadata keyring `
  --hidden-import uvicorn.loops.auto --hidden-import uvicorn.loops.asyncio `
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.http.h11_impl `
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on `
  $StartPy

Write-Host "== 7. Wagi bardsai + manifest SHA-256 =="
$Modele = Join-Path (Join-Path $KatalogBudowy "dist") "Niewidka\modele"
New-Item -ItemType Directory -Force -Path $Modele | Out-Null
Copy-Item (Join-Path $Wagi "manifest.json") $Modele -Force  # sam manifest tez musi lezec w katalogu wag
$Manifest = Get-Content -Raw (Join-Path $Wagi "manifest.json") | ConvertFrom-Json
foreach ($Plik in $Manifest.pliki.PSObject.Properties) {
  Copy-Item (Join-Path $Wagi $Plik.Name) $Modele -Force
  $Hash = (Get-FileHash (Join-Path $Modele $Plik.Name) -Algorithm SHA256).Hash.ToLower()
  if ($Hash -ne $Plik.Value) { throw "SHA-256 niezgodny dla $($Plik.Name): $Hash" }
  Write-Host ("  " + $Plik.Name + " SHA-256 OK")
}

Write-Host "== 8. Paczka ZIP (onedir) =="
$Zip = Join-Path $KatalogBudowy "Niewidka-$Wersja-windows-x64.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path (Join-Path $KatalogBudowy "dist\Niewidka") -DestinationPath $Zip
$Rozmiar = "{0:N0} MB" -f ((Get-Item $Zip).Length / 1MB)
Write-Host "  $Zip ($Rozmiar)"

Write-Host "== 9. Instalator Inno Setup (tylko gdy iscc jest) =="
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

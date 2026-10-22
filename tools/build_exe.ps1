# Windows에서 Python 설치 없이 실행되는 프로그램(EXE)을 직접 만듭니다.
# GitHub Actions의 Windows artifact에서도 검증된 빌드를 받을 수 있습니다.
#   powershell -ExecutionPolicy Bypass -File .\tools\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }
python -m unittest discover -s tests -t . -v
if ($LASTEXITCODE -ne 0) { throw "기본 테스트 실패" }
python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name NetcheckCenter --icon web\icon.ico `
  --add-data "web;web" --add-data "config\config.example.json;config" `
  --hidden-import keyring.backends.Windows --collect-submodules netmiko `
  app.py
if ($LASTEXITCODE -ne 0) { throw "EXE 빌드 실패" }
$d = "dist\NetcheckCenter"
# 이전 로컬 실행에서 생성된 운영 데이터는 배포본에 넣지 않습니다.
Remove-Item -Recurse -Force "$d\data", "$d\data-demo", "$d\보고서", "$d\보고서-demo", "$d\config\config.json" -ErrorAction SilentlyContinue
Copy-Item tools\install_autostart.ps1 $d\
Copy-Item README.md $d\
Get-ChildItem -Path . -File | Where-Object { $_.Name -like "NOTICE*" -or $_.Name -like "LICENSE*" } | Copy-Item -Destination $d
Copy-Item UPSTREAM.md $d\
New-Item -ItemType Directory -Force "$d\docs" | Out-Null
Copy-Item docs\MIGRATION_ANALYSIS.md "$d\docs\"
Set-Content -Encoding ascii "$d\데모_실행.bat" "@echo off`r`ncd /d `"%~dp0`"`r`nstart `"`" NetcheckCenter.exe --demo"
Set-Content -Encoding ascii "$d\웹_버전_실행.bat" "@echo off`r`ncd /d `"%~dp0`"`r`nstart `"`" NetcheckCenter.exe --web"
$zip = "dist\NetcheckCenter_windows_$(Get-Date -Format yyyyMMdd).zip"
Compress-Archive -Force -Path "dist\NetcheckCenter\*" -DestinationPath $zip
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content -Encoding ascii "$zip.sha256"
Write-Host $hash
Write-Host "완료: $zip  (압축을 풀고 NetcheckCenter.exe 실행)"

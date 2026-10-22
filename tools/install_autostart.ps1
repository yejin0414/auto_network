# Windows 로그인 시 점검 센터를 자동으로 켭니다(시작프로그램 바로가기).
# 사용자가 로그인 자동 시작을 선택했을 때만 이 스크립트를 실행하세요.
#   powershell -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1          등록
#   powershell -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1 -Remove  해제
param([switch]$Remove, [switch]$Inspect)
$ErrorActionPreference = "Stop"
$root = if (Test-Path (Join-Path $PSScriptRoot "NetcheckCenter.exe")) {
    $PSScriptRoot
} else {
    Split-Path $PSScriptRoot -Parent
}
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "AutoNetwork NetcheckCenter.lnk"
if ($Remove) { Remove-Item $lnk -ErrorAction SilentlyContinue; Write-Host "자동 시작을 해제했습니다."; exit }
$exe = Join-Path $root "NetcheckCenter.exe"
if (Test-Path $exe) {
    $target = $exe
    $arguments = "--minimized"
} elseif (Test-Path (Join-Path $root "app.py")) {
    $target = (Get-Command pythonw.exe -ErrorAction Stop).Source
    $arguments = "`"$root\app.py`" --minimized"
} else {
    throw "프로그램 실행 파일을 찾지 못했습니다: $root"
}
# 배포/소스 양쪽 위치를 검증할 때는 바로가기를 만들지 않습니다.
if ($Inspect) {
    @{ TargetPath = $target; Arguments = $arguments; WorkingDirectory = $root; LinkPath = $lnk } | ConvertTo-Json
    exit
}
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $target
$s.Arguments = $arguments
$s.WorkingDirectory = $root
$s.WindowStyle = 1
$s.Save()
Write-Host "등록했습니다: $lnk"
Write-Host "다음 로그인부터 최소화된 상태로 켜집니다. 작업 표시줄에서 창을 열면 됩니다."

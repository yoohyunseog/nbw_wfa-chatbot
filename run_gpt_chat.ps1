# GPT Chat Interface 실행 스크립트 (PowerShell)
# 가상환경 활성화 후 gpt_chat_interface.py 실행

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "GPT Chat Interface 실행 중..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 가상환경 활성화
Write-Host "[1/2] 가상환경 활성화 중..." -ForegroundColor Yellow
$activateScript = "E:\python_env\Scripts\Activate.ps1"

if (Test-Path $activateScript) {
    & $activateScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[오류] 가상환경 활성화 실패!" -ForegroundColor Red
        Write-Host "경로 확인: $activateScript" -ForegroundColor Red
        Read-Host "아무 키나 눌러 종료"
        exit 1
    }
} else {
    Write-Host "[오류] 가상환경 스크립트를 찾을 수 없습니다!" -ForegroundColor Red
    Write-Host "경로 확인: $activateScript" -ForegroundColor Red
    Read-Host "아무 키나 눌러 종료"
    exit 1
}

Write-Host "[2/2] GPT Chat Interface 실행 중..." -ForegroundColor Yellow
python gpt_chat_interface.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] 프로그램 실행 실패!" -ForegroundColor Red
    Read-Host "아무 키나 눌러 종료"
    exit 1
}

Write-Host ""
Write-Host "프로그램이 종료되었습니다." -ForegroundColor Green
Read-Host "아무 키나 눌러 종료"


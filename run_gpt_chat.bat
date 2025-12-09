@echo off
REM GPT Chat Interface 실행 스크립트
REM 가상환경 활성화 후 gpt_chat_interface.py 실행

echo ========================================
echo GPT Chat Interface 실행 중...
echo ========================================

REM 가상환경 활성화
echo [1/2] 가상환경 활성화 중...
call E:\python_env\Scripts\activate.bat

if errorlevel 1 (
    echo [오류] 가상환경 활성화 실패!
    echo 경로 확인: E:\python_env\Scripts\activate.bat
    pause
    exit /b 1
)

echo [2/2] GPT Chat Interface 실행 중...
python gpt_chat_interface.py

if errorlevel 1 (
    echo [오류] 프로그램 실행 실패!
    pause
    exit /b 1
)

echo.
echo 프로그램이 종료되었습니다.
pause


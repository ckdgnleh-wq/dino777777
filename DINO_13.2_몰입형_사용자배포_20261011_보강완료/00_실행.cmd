@echo off

setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul

cd /d "%~dp0"

title DINO 13.2 몰입형 

if exist "%~dp0DINO.update" (

 move /Y "%~dp0DINO.update" "%~dp0DINO.exe" >nul

 if errorlevel 1 (

  echo 실행 중인 DINO를 종료한 뒤 다시 실행해 주세요.

  pause

  exit /b 1

 )

)

if not exist "%~dp0DINO.exe" (

 echo DINO 실행파일이 없습니다. ZIP 전체를 새 폴더에 압축 해제하세요.

 pause

 exit /b 2

)

if not exist "%~dp0필수 프로그램 파일\ffmpeg.exe" (

 echo 필수 프로그램 파일이 없습니다. ZIP 전체를 압축 해제하세요.

 pause

 exit /b 3

)

set "DINO_CONSOLE_HOSTED=1"

set "DINO_DOWNLOAD_CLICK_MODE=auto"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DINO_실행상태.ps1" -Launch

set "DINO_EXIT_CODE=%ERRORLEVEL%"

if "%DINO_EXIT_CODE%"=="0" exit /b 0

echo.

echo 프로그램 실행을 확인하지 못했습니다. 위의 안내를 확인해 주세요.

pause

exit /b %DINO_EXIT_CODE%


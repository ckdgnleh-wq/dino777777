@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title DINO 13.2 몰입형 Master - Startup Diagnostics
pushd "%~dp0"
if errorlevel 1 goto bad_folder
if not exist "DINO.exe" goto missing_exe
set "DINO_DEBUG_CONSOLE=1"
set "DINO_DOWNLOAD_CLICK_MODE=auto"
set "DINO_DIAG_LOG_DIR=%~dp0logs"
if not exist "%DINO_DIAG_LOG_DIR%" mkdir "%DINO_DIAG_LOG_DIR%" 2>nul
>"%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log" echo DINO 13.2 몰입형 Master startup diagnostics
if errorlevel 1 goto fallback_log
goto run_program
:fallback_log
set "DINO_DIAG_LOG_DIR=%LOCALAPPDATA%\DINO\logs"
if not defined LOCALAPPDATA set "DINO_DIAG_LOG_DIR=%TEMP%\DINO\logs"
if not exist "%DINO_DIAG_LOG_DIR%" mkdir "%DINO_DIAG_LOG_DIR%" 2>nul
>"%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log" echo DINO 13.2 몰입형 Master startup diagnostics
if errorlevel 1 goto no_log
:run_program
echo.
echo DINO 13.2 몰입형 Master를 시작합니다. 프로그램을 사용하는 동안 이 창을 닫지 마세요.
echo 오류가 나면 오류 안내창을 확인한 뒤 이 창에 표시되는 로그를 확인하세요.
echo 로그: "%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log"
echo.
"%~dp0DINO.exe" >>"%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log" 2>&1
set "DINO_EXIT_CODE=%ERRORLEVEL%"
echo.
echo ===== DINO 종료 코드: %DINO_EXIT_CODE% =====
echo [exit_code] %DINO_EXIT_CODE%>>"%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log"
type "%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log"
echo.
echo 문제가 계속되면 위 로그 파일을 전달해 주세요. API 키나 설정파일은 보내지 마세요.
echo 로그: "%DINO_DIAG_LOG_DIR%\DINO_launch_latest.log"
pause
popd
endlocal & exit /b %DINO_EXIT_CODE%
:no_log
echo 로그 파일을 저장할 수 없습니다. 현재 콘솔에 오류를 표시합니다.
"%~dp0DINO.exe"
set "DINO_EXIT_CODE=%ERRORLEVEL%"
echo 종료 코드: %DINO_EXIT_CODE%
pause
popd
endlocal & exit /b %DINO_EXIT_CODE%
:missing_exe
echo 실행파일이 같은 폴더에 없습니다. ZIP 전체를 새 폴더에 압축 해제하세요.
pause
popd
endlocal & exit /b 2
:bad_folder
echo 프로그램 폴더를 열 수 없습니다. ZIP 밖으로 전체 압축 해제해 주세요.
pause
endlocal & exit /b 3

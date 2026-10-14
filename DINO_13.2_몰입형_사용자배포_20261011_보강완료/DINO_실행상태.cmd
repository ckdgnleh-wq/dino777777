@echo off

setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul

title DINO 13.2 몰입형 실행 상태

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DINO_실행상태.ps1"


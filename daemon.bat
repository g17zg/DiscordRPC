@echo off

chcp 65001 > nul

echo [WNPCLI] daemon starting in utf-8 encoding
wnpcli start-daemon

pause

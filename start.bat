@echo off
REM FAS 一键启动（需先配置 data/llm_config.json）
cd /d %~dp0
set PYTHON=python
if exist "E:\Miniforge.envs\Fascinator\python.exe" set PYTHON=E:\Miniforge.envs\Fascinator\python.exe
%PYTHON% -X utf8 app.py
pause

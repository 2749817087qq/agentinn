@echo off
rem agentinn - multi-model relay entry (Windows). Zero-interaction forwarder to
rem scripts/pick_model.py. Contains no business logic.
rem
rem Install shapes:
rem   1) source:    <skill>\bin\agentinn.cmd    -> skill root = parent dir
rem   2) installed: <prefix>\bin\agentinn.cmd   -> skill root = <prefix>\skills\<name>
rem Shape 2 locates the skill by SKILL.md frontmatter "name: agentinn" and never
rem hardcodes the directory name, so it works before and after the rename and is
rem unaffected by a caller-supplied %USERPROFILE%.
setlocal enableextensions

set "BIN_DIR=%~dp0"
set "SKILL_DIR="

if exist "%BIN_DIR%..\scripts\pick_model.py" set "SKILL_DIR=%BIN_DIR%.."
if not defined SKILL_DIR if exist "%BIN_DIR%..\skills" for /d %%d in ("%BIN_DIR%..\skills\*") do if not defined SKILL_DIR if exist "%%d\scripts\pick_model.py" call :probe "%%d"
if not defined SKILL_DIR if exist "%USERPROFILE%\.workbuddy\skills" for /d %%d in ("%USERPROFILE%\.workbuddy\skills\*") do if not defined SKILL_DIR if exist "%%d\scripts\pick_model.py" call :probe "%%d"
if not defined SKILL_DIR if exist "%USERPROFILE%\.workbuddy-ai\skills" for /d %%d in ("%USERPROFILE%\.workbuddy-ai\skills\*") do if not defined SKILL_DIR if exist "%%d\scripts\pick_model.py" call :probe "%%d"

if not defined SKILL_DIR goto :no_skill

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where python3 >nul 2>nul && set "PY=python3"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY goto :no_python

"%PY%" "%SKILL_DIR%\scripts\pick_model.py" %*
exit /b %ERRORLEVEL%

:probe
findstr /b /c:"name: agentinn" "%~1\SKILL.md" >nul 2>nul
if not errorlevel 1 set "SKILL_DIR=%~1"
exit /b 0

:no_skill
echo agentinn: cannot locate skill dir 1>&2
exit /b 2

:no_python
echo agentinn: python interpreter not found 1>&2
exit /b 127

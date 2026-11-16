@echo off
REM Launcher: type `hib <args>` if this folder is on PATH. Uses hib.exe when one
REM sits next to this file (or in .\bin), else routes to Python 3 via the `py -3`
REM launcher when available, else `python`.
REM
REM `hib cd|cdr|cdf` really changes THIS console's directory when the .bat is typed
REM at a cmd.exe prompt: those commands print only the target folder on stdout, and
REM a batch file runs inside the very cmd.exe that called it, so the `cd /d` below
REM outlives it. From PowerShell the .bat is a CHILD process and cannot move its
REM parent -- dot-source hib.ps1 there instead (see that file's header).
REM
REM -E -s run Python ISOLATED: ignore PYTHONPATH/PYTHONHOME and the user site dir.
REM This avoids a foreign Python stdlib (set by another app's PYTHONHOME) being
REM mixed in -- the cause of errors like "AssertionError: SRE module mismatch".
REM HIB_CONFIG / LOCALAPPDATA are still read normally (via os.environ).

if /i "%~1"=="cd"  goto :hib_chdir
if /i "%~1"=="cdr" goto :hib_chdir
if /i "%~1"=="cdf" goto :hib_chdir

if exist "%~dp0hib.exe" ("%~dp0hib.exe" %* & exit /b %errorlevel%)
if exist "%~dp0bin\hib.exe" ("%~dp0bin\hib.exe" %* & exit /b %errorlevel%)
where py >nul 2>nul && (py -3 -E -s "%~dp0hib.py" %*) || (python -E -s "%~dp0hib.py" %*)
exit /b %errorlevel%

:hib_chdir
REM Capture the printed folder (stderr -- prompts, errors -- stays on the console).
REM setlocal keeps the helper variable out of the caller's environment; `endlocal &
REM cd` is the standard way to survive it: the line is expanded BEFORE endlocal
REM runs, so the cd gets the literal path and applies to the restored environment.
setlocal
set "_hib_dir="
if exist "%~dp0hib.exe" goto :hib_chdir_exe
if exist "%~dp0bin\hib.exe" goto :hib_chdir_bin
where py >nul 2>nul && goto :hib_chdir_py
for /f "usebackq delims=" %%d in (`python -E -s "%~dp0hib.py" %*`) do set "_hib_dir=%%d"
goto :hib_chdir_done
:hib_chdir_exe
for /f "usebackq delims=" %%d in (`"%~dp0hib.exe" %*`) do set "_hib_dir=%%d"
goto :hib_chdir_done
:hib_chdir_bin
for /f "usebackq delims=" %%d in (`"%~dp0bin\hib.exe" %*`) do set "_hib_dir=%%d"
goto :hib_chdir_done
:hib_chdir_py
for /f "usebackq delims=" %%d in (`py -3 -E -s "%~dp0hib.py" %*`) do set "_hib_dir=%%d"
:hib_chdir_done
REM Nothing on stdout means it failed, or -n was used: leave the directory alone.
if not defined _hib_dir (endlocal & exit /b 1)
endlocal & cd /d "%_hib_dir%"

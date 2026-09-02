@echo off
rem =============================================================================
rem  NB_Batocera2PVE one-click pack script (Windows, requires tar.exe built-in on
rem  Win10 1803+, 7z optional for .7z output)
rem
rem  Strategy: whitelist-copy to a temp stage dir -> prune blacklist -> archive.
rem    * Includes: sources / LICENSE / README / empty config.json.example / test /
rem      tools / modules (with cache 55MB + pulse_cache 59MB) / pve_res / winres /
rem      .github (CI workflow)
rem    * Excludes: config.json (real pwd/MAC/IP), AGENTS.md (intranet creds),
rem      vncviewer.exe (RealVNC proprietary), .git, bak, Ai_Work, build, dist,
rem      __pycache__, *.pyc, tools\_diag_boot_vol.py, ai_studio_code.py
rem =============================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

set "ROOT=%~dp0.."
set "NAME=NB_Batocera2PVE"
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd-HHmmss')"`) do set "VER=%%T"
set "STAGE=%TEMP%\NB_Batocera2PVE_pack"
set "DEST=%STAGE%\%NAME%"
set "OUTDIR=%ROOT%\release"

echo [*] Project root: %ROOT%
echo [*] Stage dir   : %STAGE%

rem ------------------------- whitelist copy -------------------------
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%DEST%\modules" "%DEST%\pve_res" "%DEST%\winres" "%DEST%\test" "%DEST%\tools" "%DEST%\.github\workflows" "%OUTDIR%" 2>nul

rem root-level source / docs (never config.json / AGENTS.md / vncviewer.exe)
for %%F in (pve.py build.py README.md LICENSE requirements.txt .gitignore config.json.example) do (
    if exist "%ROOT%\%%F" (
        copy /y "%ROOT%\%%F" "%DEST%" >nul
        echo   [+] %%F
    )
)

rem modules tree (includes cache + pulse_cache), removed __pycache__ later
robocopy "%ROOT%\modules" "%DEST%\modules" /E /NFL /NDL /NJH /NJS >nul
echo   [+] modules/ ^(cache + pulse_cache^)

robocopy "%ROOT%\pve_res" "%DEST%\pve_res" /E /NFL /NDL /NJH /NJS >nul & echo   [+] pve_res/
robocopy "%ROOT%\winres"  "%DEST%\winres"  /E /NFL /NDL /NJH /NJS >nul & echo   [+] winres/
robocopy "%ROOT%\test"    "%DEST%\test"    /E /NFL /NDL /NJH /NJS >nul & echo   [+] test/

robocopy "%ROOT%\tools"   "%DEST%\tools"   /E /NFL /NDL /NJH /NJS >nul
del /q "%DEST%\tools\_diag_boot_vol.py" 2>nul
echo   [+] tools/ ^(removed _diag_boot_vol.py^)

robocopy "%ROOT%\.github" "%DEST%\.github" /E /NFL /NDL /NJH /NJS >nul & echo   [+] .github/ ^(CI workflow^)

rem ------------------------- prune blacklist -------------------------
for /d /r "%DEST%" %%D in (__pycache__) do    if exist "%%D" rmdir /s /q "%%D"
for /r  "%DEST%" %%F in (*.pyc) do            if exist "%%F" del /q "%%F"
if exist "%DEST%\modules\vnc_auto" rmdir /s /q "%DEST%\modules\vnc_auto"
if exist "%DEST%\AGENTS.md"   del /q "%DEST%\AGENTS.md"
if exist "%DEST%\config.json" del /q "%DEST%\config.json"
if exist "%DEST%\vncviewer.exe" del /q "%DEST%\vncviewer.exe"
echo [-] Pruned __pycache__/*.pyc/AGENTS.md/config.json/vncviewer.exe/modules\vnc_auto

rem ------------------------- archive -------------------------
pushd "%STAGE%"
set "SEVENZ="
where 7z   >nul 2>nul && set "SEVENZ=7z"
if not defined SEVENZ where 7za >nul 2>nul && set "SEVENZ=7za"
if not defined SEVENZ if exist "C:\Program Files\7-Zip\7z.exe" set "SEVENZ=C:\Program Files\7-Zip\7z.exe"
if not defined SEVENZ if exist "C:\Program Files (x86)\7-Zip\7z.exe" set "SEVENZ=C:\Program Files (x86)\7-Zip\7z.exe"

if "%~1"=="7z" goto :force7z
if "%~1"=="tgz" goto :forceTgz
if "%~1"=="zip" goto :forceZip

if defined SEVENZ (
    echo [*] 7z archiving...
    "%SEVENZ%" a -t7z "%OUTDIR%\%NAME%-%VER%.7z" "%NAME%" >nul
    echo [+] Done: %OUTDIR%\%NAME%-%VER%.7z
) else (
    goto :forceTgz
)
goto :verify

:force7z
if not defined SEVENZ (
    echo [-] 7z not found, falling back to tar.gz
    goto :forceTgz
)
echo [*] 7z archiving (forced)...
"%SEVENZ%" a -t7z "%OUTDIR%\%NAME%-%VER%.7z" "%NAME%" >nul
echo [+] Done: %OUTDIR%\%NAME%-%VER%.7z
goto :verify

:forceTgz
echo [*] tar.gz archiving...
tar -czf "%OUTDIR%\%NAME%-%VER%.tar.gz" "%NAME%"
echo [+] Done: %OUTDIR%\%NAME%-%VER%.tar.gz
goto :verify

:forceZip
echo [*] zip archiving...
tar -a -cf "%OUTDIR%\%NAME%-%VER%.zip" "%NAME%"
echo [+] Done: %OUTDIR%\%NAME%-%VER%.zip

:verify
echo [*] Archive listing (top):
tar -tzf "%OUTDIR%\%NAME%-%VER%.tar.gz" >nul 2>nul && tar -tzf "%OUTDIR%\%NAME%-%VER%.tar.gz" | find /c /v "" >nul
popd
rmdir /s /q "%STAGE%" 2>nul
echo [*] Output in: %OUTDIR%
endlocal
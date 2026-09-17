@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title O4U sync

:: ---------------------------------------------------------------------------
::  O4U SYNC - one step from a Stockroom export to the live site.
::
::    1. find the newest  o4u-website-images-*.zip / o4u-for-website-*.zip  in Downloads
::    2. nothing there?  -> "Nothing new", exit 0
::    3. unzip: images -> website\images\, stockroom.json -> project root
::    4. build the catalogue (stops here if the build fails - never publishes a bad build)
::    5. git add / commit / push   (Netlify deploys the push automatically)
::    6. move the ZIP into Downloads\synced\ so it is never processed twice
::
::  Run by double-click (pauses at the end) or by the "O4U Sync" scheduled task
::  with  /auto  (no pauses, appends to sync.log).
:: ---------------------------------------------------------------------------

set "AUTO="
if /i "%~1"=="/auto" set "AUTO=1"
set "LOG=%~dp0sync.log"
set "DL=%O4U_DOWNLOADS%"
if not defined DL set "DL=%USERPROFILE%\Downloads"
set "SYNCED=%DL%\synced"
set "TMPX=%TEMP%\o4u-sync-extract"

if not defined AUTO (
  echo.
  echo ================= O4U SYNC =================
)

:: ---- 1. newest ZIP -------------------------------------------------------
set "ZIP="
for /f "delims=" %%f in ('dir /b /a-d /o-d "%DL%\o4u-website-images-*.zip" "%DL%\o4u-for-website-*.zip" 2^>nul') do (
  if not defined ZIP set "ZIP=%DL%\%%f"
)
if not defined ZIP (
  echo Nothing new - no o4u-website-images-*.zip or o4u-for-website-*.zip in %DL%
  goto :quiet_exit
)
call :log "==== %DATE% %TIME:~0,5%  found %ZIP%"
echo Found export: %ZIP%

where python >nul 2>nul || (call :fail "Python is not installed or not on PATH. Install it from python.org (tick 'Add to PATH')." & goto :end_fail)
where git    >nul 2>nul || (call :fail "Git is not installed. Install it from git-scm.com." & goto :end_fail)

:: ---- 3. unzip ------------------------------------------------------------
echo [1/4] Unzipping ...
if exist "%TMPX%" rmdir /s /q "%TMPX%"
mkdir "%TMPX%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TMPX%' -Force; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (call :fail "The ZIP could not be opened. Download it again from Stockroom." & goto :end_fail)

set "SRJSON="
for /f "delims=" %%f in ('dir /b /s /a-d "%TMPX%\stockroom.json" 2^>nul') do if not defined SRJSON set "SRJSON=%%f"
if not defined SRJSON (call :fail "stockroom.json is not inside this ZIP. Use the 'Download for website' button in Stockroom." & goto :end_fail)
copy /y "%SRJSON%" "%~dp0stockroom.json" >nul

if not exist "website\images" mkdir "website\images"
set /a NIMG=0
for /r "%TMPX%" %%f in (*.jpg *.jpeg *.png *.webp) do (
  copy /y "%%f" "website\images\%%~nxf" >nul
  set /a NIMG+=1
)
echo       stockroom.json + !NIMG! image(s) copied into the project.
call :log "unzipped: stockroom.json + !NIMG! images"

:: ---- 4. build ------------------------------------------------------------
echo [2/4] Building the catalogue ...
python scripts\build_catalogue.py --quiet > "%TEMP%\o4u-build.txt" 2>&1
set "BUILD_RC=%ERRORLEVEL%"
type "%TEMP%\o4u-build.txt"
type "%TEMP%\o4u-build.txt" >> "%LOG%"
if not "%BUILD_RC%"=="0" (
  call :fail "The build FAILED, so nothing was published. The errors are listed above. Re-export from Stockroom after fixing them."
  git checkout -q -- stockroom.json >nul 2>nul
  call :park "failed"
  goto :end_fail
)
set "N=?"
for /f "tokens=2" %%n in ('findstr /c:"published products" website\products.js') do set "N=%%n"
echo       OK - products.js has !N! products.

:: ---- 5. commit + push ----------------------------------------------------
echo [3/4] Saving and publishing ...
git add -A >nul 2>nul
git diff --cached --quiet
if not errorlevel 1 (
  echo       Nothing changed on the site - this export matched what is already live.
  call :park "synced"
  goto :done_line
)
set "TS="
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set "TS=%%t"
if not defined TS set "TS=%DATE% %TIME:~0,5%"
git commit -q -m "stock: !N! products, !TS!"
if errorlevel 1 (call :fail "Could not save the snapshot (git commit failed)." & goto :end_fail)
git push >> "%LOG%" 2>&1
if errorlevel 1 (
  call :fail "Publishing FAILED (git push). The snapshot is saved on this PC. Check the internet / GitHub sign-in and run sync.bat again - it will only push."
  goto :end_fail
)
echo       Pushed. Netlify is deploying it now.

:: ---- 6. park the ZIP -----------------------------------------------------
call :park "synced"

:done_line
echo.
echo ==== !N! products are now live at https://only4you-store.netlify.app (allow about a minute) ====
call :log "OK: !N! products live"
if not defined AUTO pause
exit /b 0

:quiet_exit
if not defined AUTO pause
exit /b 0

:end_fail
echo ==== STOPPED - see the message above. ====
if not defined AUTO pause
exit /b 1

:: ---- helpers ---------------------------------------------------------------
:fail
echo.
echo XX %~1
call :log "FAILED: %~1"
goto :eof

:park
set "DEST=%SYNCED%"
if /i not "%~1"=="synced" set "DEST=%SYNCED%\%~1"
if not exist "%DEST%" mkdir "%DEST%" >nul 2>nul
move /y "%ZIP%" "%DEST%\" >nul 2>nul
if exist "%TMPX%" rmdir /s /q "%TMPX%"
echo [4/4] ZIP moved to %DEST%
goto :eof

:log
>> "%LOG%" echo %~1
goto :eof

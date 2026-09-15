@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title O4U sync

echo.
echo ================= O4U SYNC =================
echo  Builds the catalogue from the workbook and
echo  stockroom.json, then publishes it to the site.
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo XX Python is not installed or not on PATH.
  echo    Install it from python.org, tick "Add to PATH", then run this again.
  goto :fail
)
where git >nul 2>nul
if errorlevel 1 (
  echo XX Git is not installed. Install it from git-scm.com, then run this again.
  goto :fail
)

echo [1/4] Building the catalogue ...
python scripts\build_catalogue.py --quiet
if errorlevel 1 (
  echo.
  echo XX The build FAILED, so nothing was published.
  echo    The errors are listed above. Fix them in the workbook or stockroom.json,
  echo    then run sync.bat again.
  goto :fail
)
echo       OK - products.js is up to date.
echo.

echo [2/4] Collecting changes ...
git add -A >nul 2>nul
git diff --cached --quiet
if not errorlevel 1 (
  echo       Nothing has changed since the last sync. The site is already current.
  goto :done
)
git diff --cached --stat | findstr /r /c:"file.*changed"
echo.

set "N=?"
for /f "tokens=2" %%n in ('findstr /c:"published products" website\products.js') do set "N=%%n"
set "TS="
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set "TS=%%t"
if not defined TS set "TS=%date% %time:~0,5%"

echo [3/4] Saving a snapshot: "stock: %N% products, %TS%" ...
git commit -q -m "stock: %N% products, %TS%"
if errorlevel 1 (
  echo XX Could not save the snapshot. Nothing was published.
  echo    If this is the first time on this computer, run these once:
  echo      git config --global user.name  "Only 4 You"
  echo      git config --global user.email "only4yousince2024@gmail.com"
  goto :fail
)
echo       OK
echo.

echo [4/4] Publishing (git push) ...
git push
if errorlevel 1 (
  echo.
  echo XX Publishing FAILED. The snapshot is saved on this computer but the site
  echo    was NOT updated. Check the internet connection and the GitHub login,
  echo    then run sync.bat again - it will only push, nothing is lost.
  goto :fail
)
echo.
echo ==== DONE - %N% products published. The site updates in about a minute. ====
goto :done

:fail
echo.
echo ==== STOPPED - see the message above. ====
pause
exit /b 1

:done
echo.
pause
exit /b 0

@echo off
setlocal
title Multi-Tenant E-commerce SaaS - Dev Launcher

REM Always work from the folder this script lives in (handles spaces in the
REM path - the repository directory is "PBL project").
cd /d "%~dp0"

echo.
echo  ============================================================
echo   Multi-Tenant E-commerce SaaS  -  local dev launcher
echo  ============================================================
echo.

REM ---- preflight checks ------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python was not found on PATH.
    goto :fail
)
where node >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js was not found on PATH.
    goto :fail
)

if exist "frontend\node_modules" goto :deps_done
echo  [setup] Installing frontend dependencies - first run only...
pushd frontend
call npm install
if errorlevel 1 goto :deps_failed
popd
goto :deps_done
:deps_failed
popd
goto :fail
:deps_done
echo.

REM ---- database ---------------------------------------------------------
echo  [1/3] Applying database migrations...
python backend\manage.py migrate --noinput
if errorlevel 1 goto :fail

echo  [2/3] Seeding demo data - idempotent, skips anything that exists...
python seed_demo.py
if errorlevel 1 goto :fail
echo.

REM ---- services (each in its own console window) ------------------------
echo  [3/3] Starting services...
start "SaaS - Django backend (8000)" cmd /k python backend\manage.py runserver 0.0.0.0:8000
start "SaaS - React frontend (5173)" cmd /k "cd frontend && npm run dev"

REM ---- optional: DNS simulator (Administrator required for port 53) ------
python -c "import dnslib" >nul 2>&1
if errorlevel 1 goto :dns_no_lib
fltmc >nul 2>&1
if errorlevel 1 goto :dns_no_admin
start "SaaS - DNS simulator (53)" cmd /k python dns_simulator.py
goto :dns_done

:dns_no_lib
echo  [i] DNS simulator skipped - the dnslib package is not installed.
echo      Install it with:  pip install dnslib
goto :dns_done

:dns_no_admin
echo  [i] DNS simulator skipped - Administrator rights are needed for port 53.
echo      localhost works without it:   http://localhost:5173
echo      For branded hosts such as acme.local-saas.com, right-click
echo      start_dev.bat and choose "Run as administrator", or add entries
echo      to C:\Windows\System32\drivers\etc\hosts (see README.md).
goto :dns_done

:dns_done
echo.
echo  ------------------------------------------------------------
echo   Ready. Open one of these in your browser:
echo.
echo     Storefront ....... http://localhost:5173
echo     Vendor dashboard . http://localhost:5173/admin/login
echo     SuperAdmin ....... http://localhost:5173/superadmin/login
echo.
echo   You can close this launcher - the service windows stay open.
echo   Stop the services by closing those windows.
echo  ------------------------------------------------------------
echo.
if /i "%~1"=="/nopause" exit /b 0
pause
exit /b 0

:fail
echo.
echo  [ERROR] Startup failed - see the message above.
if /i "%~1"=="/nopause" exit /b 1
pause
exit /b 1

@echo off
setlocal EnableExtensions

rem ============================================================
rem  MultiRoofs Windows Build
rem
rem  Expected layout:
rem    <PROJECT_ROOT>\
rem      main.py
rem      UI\
rem      venv\
rem      multiroofs-build\
rem        MultiRoofs_Windows\
rem          build_windows.bat   (this file)
rem          multiroof.spec
rem          installer\
rem ============================================================

rem ---------- Paths ----------
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..\..") do set "PROJECT_ROOT=%%~fI"

rem Name of the virtual environment folder in the project root
set "VENV_DIR=%PROJECT_ROOT%\venv"

rem Build output (build, dist, installer_output) is created next to this file
cd /d "%SCRIPT_DIR%"

rem ---------- ANSI colors (Windows 10 and later) ----------
for /f %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"
set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "RESET=%ESC%[0m"

echo %CYAN%=== MultiRoofs Windows Build ===%RESET%
echo Project root: %PROJECT_ROOT%
echo Build folder: %SCRIPT_DIR%

rem ---------- Check required files ----------
set "MISSING="

rem Application files, in the project root
for %%F in (
    "main.py"
    "UI\MainWindow.py"
    "UI\DialogSettings.py"
    "UI\DialogAbout.py"
    "UI\config_io.py"
    "UI\mainWindow.ui"
    "UI\dialogSettings.ui"
    "UI\dialogAbout.ui"
    "UI\resources\logo_interreg.png"
    "UI\resources\logo_ulb.png"
    "UI\resources\logo_mlg.png"
    "UI\resources\uicityjson_icon.ico"
) do call :check_file "%PROJECT_ROOT%" "%%~F"

rem Build files, next to this script
for %%F in (
    "multiroofs.spec"
    "installer\installer_windows.iss"
) do call :check_file "%SCRIPT_DIR%" "%%~F"

if defined MISSING exit /b 1

rem ---------- Check Python launcher ----------
where py >nul 2>&1
if errorlevel 1 (
    echo %RED%Python launcher 'py' was not found. Install 64-bit Python 3.11+ first.%RESET%
    exit /b 1
)

rem ---------- Virtual environment ----------
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment in %VENV_DIR%...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :fail_venv
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"

"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :fail_pip
"%PYTHON%" -m pip install -r "%PROJECT_ROOT%\requirements.txt"
if errorlevel 1 goto :fail_pip

rem ---------- Clean previous output ----------
if exist "%SCRIPT_DIR%\build\" rmdir /s /q "%SCRIPT_DIR%\build"
if exist "%SCRIPT_DIR%\dist\" rmdir /s /q "%SCRIPT_DIR%\dist"
if exist "%SCRIPT_DIR%\installer_output\" rmdir /s /q "%SCRIPT_DIR%\installer_output"

rem ---------- PyInstaller ----------
echo %CYAN%Building application with PyInstaller...%RESET%
"%PYINSTALLER%" --noconfirm --clean "%SCRIPT_DIR%\multiroofs.spec"
if errorlevel 1 goto :fail_pyinstaller

set "EXE=%SCRIPT_DIR%\dist\MultiRoofs\MultiRoofs.exe"
if not exist "%EXE%" goto :fail_pyinstaller

echo %GREEN%Executable created: %EXE%%RESET%

rem ---------- Find Inno Setup ----------
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo(
    echo %YELLOW%Inno Setup 6 not found.%RESET%
    echo The executable is ready, but the installer was not created.
    echo Install Inno Setup 6 and run build_windows.bat again.
    exit /b 0
)

rem ---------- Inno Setup ----------
echo %CYAN%Building installer with Inno Setup...%RESET%
"%ISCC%" "%SCRIPT_DIR%\installer\installer_windows.iss"
if errorlevel 1 goto :fail_inno

set "INSTALLER=%SCRIPT_DIR%\installer_output\MultiRoofs_CityJSON_Setup.exe"
echo %INSTALLER%
if not exist "%INSTALLER%" goto :fail_inno

echo(
echo %GREEN%SUCCESS%RESET%
echo Application: %EXE%
echo Installer:   %INSTALLER%
exit /b 0

rem ---------- Subroutines ----------
:check_file
if not exist "%~1\%~2" (
    if not defined MISSING echo %RED%Missing required files:%RESET%
    set "MISSING=1"
    echo %RED%  %~1\%~2%RESET%
)
exit /b 0

rem ---------- Error handlers ----------
:fail_venv
echo %RED%Could not create the virtual environment in %VENV_DIR%%RESET%
exit /b 1

:fail_pip
echo %RED%pip could not install the dependencies from requirements-build.txt%RESET%
exit /b 1

:fail_pyinstaller
echo %RED%PyInstaller did not create dist\MultiRoof\MultiRoof.exe%RESET%
exit /b 1

:fail_inno
echo %RED%Inno Setup did not create installer_output\MultiRoofSetup.exe%RESET%
exit /b 1
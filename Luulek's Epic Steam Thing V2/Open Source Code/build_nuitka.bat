@echo off
REM Batch file to build an EXE using Nuitka

REM Set your script filename
set SCRIPT=main.py

REM Set EXE name
set EXE_NAME=Luulek's Epic Steam Thing V2.exe

REM Clean previous builds
if exist "%SCRIPT%.build" rmdir /s /q "%SCRIPT%.build"
if exist dist rmdir /s /q dist

REM Build the EXE using Nuitka
python -m pip install --upgrade pip
python -m pip install nuitka --upgrade

python -m nuitka ^
    --standalone ^
    --windows-disable-console ^
    --include-data-dir=Files=Files ^
    --icon=Files\Icon.ico ^
    --output-dir=dist ^
    --assume-yes-for-downloads ^
    --remove-output ^
    --output-filename="%EXE_NAME%" ^
    %SCRIPT%

echo Build complete. Check the dist folder for "%EXE_NAME%".
pause

@echo off
REM DEAMONMARIA V2 - Quick Install for Windows
REM Automatyczna instalacja dla Windows

echo ======================================================================
echo    DEAMONMARIA V2 - Automatyczna instalacja (Windows)
echo ======================================================================
echo.

REM Sprawdź Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python nie znaleziony. Zainstaluj Python 3.8+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python znaleziony
python --version

REM Sprawdź Ollama
where ollama >nul 2>&1
if errorlevel 1 (
    echo.
    echo [UWAGA] Ollama nie znaleziona
    echo.
    echo Zainstaluj Ollama z:
    echo https://ollama.ai/download/windows
    echo.
    echo Po instalacji uruchom ponownie ten skrypt.
    pause
    exit /b 1
)

echo [OK] Ollama zainstalowana
ollama --version

REM Sprawdź czy Ollama działa
echo.
echo Sprawdzam czy Ollama działa...
ollama list >nul 2>&1
if errorlevel 1 (
    echo [UWAGA] Ollama nie odpowiada. Uruchamiam serwer...
    start "Ollama Server" ollama serve
    timeout /t 5 /nobreak >nul
)

REM Pobierz model
echo.
echo Sprawdzam model llama3.1:8b...
ollama list | findstr "llama3.1:8b" >nul
if errorlevel 1 (
    echo Pobieram model llama3.1:8b ^(to moze chwile potrwac^)...
    ollama pull llama3.1:8b
) else (
    echo [OK] Model llama3.1:8b juz pobrany
)

REM Utworz projekt
echo.
echo Tworze strukture projektu...
python setup_deamonmaria_v2.py

REM Zainstaluj zaleznosci
echo.
echo Instaluje zaleznosci Python...
cd maria_core
python -m pip install -r requirements.txt --quiet

echo.
echo ======================================================================
echo    Instalacja zakonczona!
echo ======================================================================
echo.
echo Nastepne kroki:
echo.
echo 1. Dodaj pliki .txt do nauki:
echo    maria_core\input\
echo.
echo 2. Uruchom system:
echo    cd maria_core
echo    python orchestrator.py
echo.
echo 3. Lub zintegruj z maria_daemon.py:
echo    Zobacz: maria_core\README.md
echo.
pause

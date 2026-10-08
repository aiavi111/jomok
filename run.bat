@echo off
rem Запуск одной командой для Windows.
rem   run.bat          - запустить сервер на http://localhost:8080 (при первом запуске поставит всё нужное)
rem   run.bat dev      - то же, но с DEV_MODE=1: Mini App открывается в обычном браузере (только для теста!)
rem   run.bat demo     - собрать пробную книгу без сервера
rem   run.bat check    - проверить ключи из .env
rem   run.bat botprofile - оформить бота: описание, команды, кнопка меню (run.bat botprofile --name - ещё и имя)
rem   run.bat story    - показать сказку, которую пишет выбранный в .env текстовый провайдер (без картинок)
rem   run.bat test     - запустить автоматические проверки
setlocal enableextensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

rem 1. Ищем Python 3.11 или новее
set "PY="
where py >nul 2>nul && (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
  )
)
if not defined PY (
  echo Не нашёл Python версии 3.11 или новее.
  echo Установите его с https://www.python.org/downloads/ и поставьте галочку "Add python.exe to PATH".
  echo Потом закройте это окно и запустите run.bat снова.
  pause
  exit /b 1
)

rem 2. Файл с настройками
if not exist .env (
  copy /y .env.example .env >nul
  echo Создал файл .env из шаблона. Пока ключей нет - всё работает на заглушках.
)

rem 3. Виртуальное окружение и зависимости
if not exist .venv\Scripts\python.exe (
  echo Создаю виртуальное окружение ^(один раз^)...
  %PY% -m venv .venv
  if errorlevel 1 ( echo Не получилось создать окружение. & pause & exit /b 1 )
)

set "MODE=%~1"
if "%MODE%"=="" set "MODE=start"
set "REQ=requirements.txt"
set "STAMP=.venv\.deps-main"
if "%MODE%"=="test" (
  set "REQ=requirements-dev.txt"
  set "STAMP=.venv\.deps-dev"
)

set "NEWHASH="
for /f %%H in ('.venv\Scripts\python.exe -c "import hashlib; print(hashlib.sha256(open(r'%REQ%','rb').read()).hexdigest())"') do set "NEWHASH=%%H"
set "OLDHASH="
if exist "%STAMP%" set /p OLDHASH=<"%STAMP%"
if not "%NEWHASH%"=="%OLDHASH%" (
  echo Ставлю зависимости ^(один раз, около минуты^)...
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip >nul 2>nul
  .venv\Scripts\python.exe -m pip install --quiet -r %REQ%
  if errorlevel 1 ( echo Не получилось поставить зависимости. Проверьте интернет и повторите. & pause & exit /b 1 )
  >"%STAMP%" echo %NEWHASH%
)

if "%MODE%"=="start" goto start
if "%MODE%"=="dev" goto dev
if "%MODE%"=="demo" goto demo
if "%MODE%"=="check" goto check
if "%MODE%"=="story" goto story
if "%MODE%"=="botprofile" goto botprofile
if "%MODE%"=="test" goto test
echo Не знаю такой команды: %MODE%
echo Можно: run.bat ^| dev ^| demo ^| check ^| story ^| botprofile ^| test
exit /b 1

:start
.venv\Scripts\python.exe -m app.main
goto end

:dev
set DEV_MODE=1
echo DEV_MODE=1 на этот запуск: откройте http://localhost:8080 в браузере.
.venv\Scripts\python.exe -m app.main
goto end

:demo
.venv\Scripts\python.exe demo.py %2 %3 %4
goto end

:check
.venv\Scripts\python.exe check_keys.py
goto end

:botprofile
.venv\Scripts\python.exe setup_bot.py %2
goto end

:story
.venv\Scripts\python.exe story_preview.py %2 %3
goto end

:test
.venv\Scripts\python.exe -m pytest -q
goto end

:end
if errorlevel 1 pause
endlocal

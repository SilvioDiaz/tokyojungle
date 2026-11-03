@echo off
setlocal
rem ==========================================================================
rem  Tokyo Jungle Recompiled - build automatico
rem
rem  Coloque este arquivo numa pasta junto com:
rem    - a pasta do jogo extraido (com USRDIR e PARAM.SFO dentro)
rem    - o arquivo UP9000-NPUA80523_00-TOKYOJUNGLE00001.rap
rem  e de dois cliques. No fim aparece o TokyoJungle.exe nesta pasta.
rem ==========================================================================
set "ROOT=%~dp0"
set "REPO=https://github.com/SilvioDiaz/tokyojungle.git"
if defined TJ_REPO set "REPO=%TJ_REPO%"
set "SRC=%ROOT%.build\tokyojungle"

where git >nul 2>nul
if errorlevel 1 (
    echo Instalando o Git...
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
)

if not exist "%SRC%\.git" (
    echo Baixando o projeto de %REPO% ...
    git clone -q "%REPO%" "%SRC%" || goto :erro
) else (
    echo Atualizando o projeto...
    git -C "%SRC%" pull -q --ff-only
    if errorlevel 1 (
        echo.
        echo AVISO: nao foi possivel baixar a versao nova. O build continua com a versao
        echo que ja estava aqui. Para baixar tudo de novo, apague a pasta .build.
        echo WARNING: could not download the new version. Building the copy already
        echo here. To download everything again, delete the .build folder.
        echo.
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%\scripts\tj_build_all.ps1" -Root "%ROOT%." %*
if errorlevel 1 goto :erro
echo.
pause
exit /b 0

:erro
echo.
echo O build parou com erro. Veja o arquivo build.log nesta pasta.
pause
exit /b 1

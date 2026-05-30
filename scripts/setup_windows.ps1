param(
    [string]$OllamaModel = "qwen2.5:0.5b",
    [switch]$AllowUnsupportedPython
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$PythonExe = Join-Path $Venv "Scripts\python.exe"
$Bin = Join-Path $Root "backend\bin"
$WhisperDir = Join-Path $Bin "whisper"
$PiperDir = Join-Path $Bin "piper"

function Resolve-Python {
    foreach ($Version in @("-3.12", "-3.11", "-3.10")) {
        try {
            $Result = & py $Version --version 2>$null
            $ExitCode = $LASTEXITCODE
        } catch {
            $Result = $null
            $ExitCode = 1
        }

        if ($ExitCode -eq 0 -and $Result) {
            return @("py", $Version)
        }
    }

    if ($AllowUnsupportedPython) {
        try {
            $Result = & py -3 --version 2>$null
            $ExitCode = $LASTEXITCODE
        } catch {
            $Result = $null
            $ExitCode = 1
        }

        if ($ExitCode -eq 0 -and $Result) {
            Write-Warning "Using $Result. Some AI wheels may not support this yet; Python 3.11 or 3.12 is recommended."
            return @("py", "-3")
        }
    }

    throw "No supported Python runtime found. Install Python 3.11 or 3.12, then run this script again."
}

$PythonCommand = Resolve-Python
$PythonLauncher = $PythonCommand[0]
$PythonVersion = $PythonCommand[1]

if (-not (Test-Path $Venv)) {
    if ($PythonVersion) {
        & $PythonLauncher $PythonVersion -m venv $Venv
    } else {
        & $PythonLauncher -m venv $Venv
    }
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $Root "backend\requirements.txt")
& $PythonExe (Join-Path $Root "scripts\download_models.py")

New-Item -ItemType Directory -Force -Path $WhisperDir, $PiperDir | Out-Null

$WhisperExe = Join-Path $WhisperDir "Release\whisper-cli.exe"
if (-not (Test-Path $WhisperExe)) {
    $WhisperZip = Join-Path $Bin "whisper-bin-x64.zip"
    Invoke-WebRequest `
        -Uri "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-bin-x64.zip" `
        -OutFile $WhisperZip
    Expand-Archive -Path $WhisperZip -DestinationPath $WhisperDir -Force
    Remove-Item -LiteralPath $WhisperZip -ErrorAction SilentlyContinue
}

$PiperExe = Join-Path $PiperDir "piper\piper.exe"
if (-not (Test-Path $PiperExe)) {
    $PiperZip = Join-Path $Bin "piper_windows_amd64.zip"
    Invoke-WebRequest `
        -Uri "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip" `
        -OutFile $PiperZip
    Expand-Archive -Path $PiperZip -DestinationPath $PiperDir -Force
    Remove-Item -LiteralPath $PiperZip -ErrorAction SilentlyContinue
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    ollama pull $OllamaModel
} else {
    Write-Warning "Ollama was not found on PATH. Install Ollama, then run: ollama pull $OllamaModel"
}

Write-Host "Setup complete."
Write-Host "Downloaded local speech binaries under backend\bin."
Write-Host "Set ECHO_WHISPER_CPP_BIN and ECHO_PIPER_BIN only if you want to use different binaries."
Write-Host "Run: .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

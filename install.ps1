$ErrorActionPreference = 'Stop'

if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $global:PSNativeCommandUseErrorActionPreference = $true
}

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "    $Description" -ForegroundColor DarkGray
    & $Command

    if ($LASTEXITCODE -ne 0) {
        throw "Kommandot misslyckades: $Description (exit code $LASTEXITCODE)"
    }
}

function Assert-Path {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

if (-not $IsLinux) {
    throw "Detta skript ar gjort for Ubuntu Linux / WSL och maste koras med PowerShell pa Linux."
}

$ProjectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Get-Location).Path
}

Set-Location -LiteralPath $ProjectRoot

Assert-Path -Path (Join-Path $ProjectRoot 'requirements.txt') -Message 'requirements.txt saknas i projektroten.'
Assert-Path -Path (Join-Path $ProjectRoot '.env.example') -Message '.env.example saknas i projektroten.'
Assert-Path -Path (Join-Path $ProjectRoot 'chat-gui/package.json') -Message 'chat-gui/package.json saknas.'

Write-Host "NOVA AI installeras fran: $ProjectRoot" -ForegroundColor Green

Write-Step 'Systemuppdatering och systempaket'
Invoke-Native -Description 'sudo apt update' -Command {
    sudo apt update
}

Invoke-Native -Description 'Installerar systempaket och byggverktyg' -Command {
    sudo apt install -y git curl unzip portaudio19-dev python3-dev python3-pip python3-venv build-essential gfortran pkg-config libopenblas-dev software-properties-common
}

Write-Step 'Node.js och Python 3.11'
Invoke-Native -Description 'Lagger till deadsnakes PPA' -Command {
    sudo add-apt-repository -y ppa:deadsnakes/ppa
}

Invoke-Native -Description 'sudo apt update efter PPA' -Command {
    sudo apt update
}

Invoke-Native -Description 'Installerar Python 3.11' -Command {
    sudo apt install -y python3.11 python3.11-venv python3.11-dev
}

Invoke-Native -Description 'Installerar NodeSource for Node.js v22' -Command {
    bash -lc 'curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -'
}

Invoke-Native -Description 'Installerar Node.js v22' -Command {
    sudo apt install -y nodejs
}

Write-Step 'Projektinstallningar'
$EnvPath = Join-Path $ProjectRoot '.env'
$EnvExamplePath = Join-Path $ProjectRoot '.env.example'

if (Test-Path -LiteralPath $EnvPath) {
    Write-Host '    .env finns redan, hoppar over kopiering.' -ForegroundColor DarkGray
}
else {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    Write-Host '    Skapade .env fran .env.example.' -ForegroundColor DarkGray
}

Write-Step 'Python virtuell miljo (.venv)'
$VenvPath = Join-Path $ProjectRoot '.venv'

if (Test-Path -LiteralPath $VenvPath) {
    Write-Host '    Tar bort befintlig .venv.' -ForegroundColor DarkGray
    Remove-Item -LiteralPath $VenvPath -Recurse -Force
}

Invoke-Native -Description 'Skapar .venv med Python 3.11' -Command {
    python3.11 -m venv .venv
}

$VenvPython = Join-Path $VenvPath 'bin/python'
$VenvPip = Join-Path $VenvPath 'bin/pip'

Assert-Path -Path $VenvPython -Message 'Kunde inte hitta .venv/bin/python efter venv-skapande.'
Assert-Path -Path $VenvPip -Message 'Kunde inte hitta .venv/bin/pip efter venv-skapande.'

Invoke-Native -Description 'Uppdaterar pip i .venv' -Command {
    & $VenvPython -m pip install --upgrade pip
}

Invoke-Native -Description 'Installerar Python-beroenden fran requirements.txt' -Command {
    & $VenvPip install -r requirements.txt
}

Write-Step 'Frontend (chat-gui)'
$ChatGuiPath = Join-Path $ProjectRoot 'chat-gui'
Push-Location -LiteralPath $ChatGuiPath
try {
    Invoke-Native -Description 'Korer npm install i chat-gui' -Command {
        npm install
    }

    $ChromeSandboxPath = Join-Path $ChatGuiPath 'node_modules/electron/dist/chrome-sandbox'
    if (Test-Path -LiteralPath $ChromeSandboxPath) {
        Invoke-Native -Description 'Satter root-agare pa Electron chrome-sandbox' -Command {
            sudo chown root:root $ChromeSandboxPath
        }

        Invoke-Native -Description 'Satter setuid-behorighet pa Electron chrome-sandbox' -Command {
            sudo chmod 4755 $ChromeSandboxPath
        }
    }
    else {
        Write-Warning "Electron chrome-sandbox hittades inte pa: $ChromeSandboxPath"
    }
}
finally {
    Pop-Location
}

Write-Step 'Vosk-modell (rostmodellen)'
$VoskPath = Join-Path $ProjectRoot 'models/vosk'
$VoskZipName = 'vosk-model-small-en-us-0.15.zip'
$VoskZipPath = Join-Path $VoskPath $VoskZipName
$VoskModelPath = Join-Path $VoskPath 'vosk-model-small-en-us-0.15'
$VoskUrl = "https://alphacephei.com/vosk/models/$VoskZipName"

New-Item -ItemType Directory -Path $VoskPath -Force | Out-Null

if (Test-Path -LiteralPath $VoskModelPath) {
    Write-Host '    Vosk-modellen finns redan uppackad, hoppar over nedladdning.' -ForegroundColor DarkGray
}
else {
    if (-not (Test-Path -LiteralPath $VoskZipPath)) {
        Invoke-Native -Description 'Laddar ner Vosk-modellen' -Command {
            curl -L --fail --output $VoskZipPath $VoskUrl
        }
    }
    else {
        Write-Host '    Zip-filen finns redan, hoppar over nedladdning.' -ForegroundColor DarkGray
    }

    Invoke-Native -Description 'Packar upp Vosk-modellen' -Command {
        unzip -q $VoskZipPath -d $VoskPath
    }

    Remove-Item -LiteralPath $VoskZipPath -Force
    Write-Host '    Tog bort zip-filen efter uppackning.' -ForegroundColor DarkGray
}

Write-Host ''
Write-Host 'NOVA AI-installationen ar klar!' -ForegroundColor Green
Write-Host ''
Write-Host 'Starta backenden:' -ForegroundColor Green
Write-Host '  source .venv/bin/activate'
Write-Host '  python app.py'
Write-Host ''
Write-Host 'Starta frontenden:' -ForegroundColor Green
Write-Host '  cd chat-gui'
Write-Host '  DISPLAY=:0 npm run dev'
Write-Host ''

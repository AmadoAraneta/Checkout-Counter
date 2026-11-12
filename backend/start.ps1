$ErrorActionPreference = 'Stop'
$backendPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw 'Backend environment missing. Run: python -m venv backend/.venv, then backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt (from the project root).'
}
Push-Location $PSScriptRoot
try {
    $backendEnvFile = Join-Path $PSScriptRoot '.env'
    $backendArguments = @('-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '5000', '--reload')
    if (Test-Path -LiteralPath $backendEnvFile) {
        $backendArguments += @('--env-file', $backendEnvFile)
    }
    & $backendPython @backendArguments
} finally {
    Pop-Location
}

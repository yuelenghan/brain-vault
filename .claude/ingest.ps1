$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command py -ErrorAction SilentlyContinue

if ($python) {
    & py -3 (Join-Path $scriptDir "ingest.py")
    exit $LASTEXITCODE
}

& python (Join-Path $scriptDir "ingest.py")
exit $LASTEXITCODE

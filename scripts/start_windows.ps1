$ErrorActionPreference = "Stop"

$ContainerName = "finally"
$ImageName = "finally"
$Port = 8000

Set-Location "$PSScriptRoot\.."

$NeedsBuild = $args -contains "--build"
$NoOpen = $args -contains "--no-open"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host ".env not found — copying from .env.example. Edit it to add API keys."
        Copy-Item ".env.example" ".env"
    } else {
        Write-Error ".env file is required (see .env.example)."
        exit 1
    }
}

if (-not $NeedsBuild) {
    docker image inspect $ImageName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $NeedsBuild = $true }
}

if ($NeedsBuild) {
    Write-Host "Building image..."
    docker build -t $ImageName .
}

# Stop existing container if running (idempotent)
docker rm -f $ContainerName 2>$null | Out-Null

docker run -d `
    --name $ContainerName `
    -p "${Port}:8000" `
    -v finally-data:/app/db `
    --env-file .env `
    $ImageName | Out-Null

Write-Host "FinAlly running at http://localhost:$Port"

if (-not $NoOpen) {
    Start-Process "http://localhost:$Port"
}

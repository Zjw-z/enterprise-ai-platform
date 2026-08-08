param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [string]$DatabaseUrl = $env:EAP_DATABASE_URL,
    [string]$MinioAlias = "eap",
    [string]$MinioBucket = "enterprise-ai"
)

$ErrorActionPreference = "Stop"
$resolvedDestination = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $resolvedDestination | Out-Null

if (-not $DatabaseUrl) {
    throw "DatabaseUrl or EAP_DATABASE_URL is required."
}
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw "pg_dump is not available on PATH."
}

$databaseFile = Join-Path $resolvedDestination "postgres.dump"
& pg_dump --format=custom --file=$databaseFile $DatabaseUrl
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL backup failed."
}

$configDirectory = Join-Path $resolvedDestination "configuration"
New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
Copy-Item -LiteralPath "config.yaml" -Destination $configDirectory
Copy-Item -LiteralPath "config.production.yaml" -Destination $configDirectory
Copy-Item -LiteralPath "alembic.ini" -Destination $configDirectory

if (Get-Command mc -ErrorAction SilentlyContinue) {
    $minioDirectory = Join-Path $resolvedDestination "minio"
    & mc mirror "$MinioAlias/$MinioBucket" $minioDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "MinIO backup failed."
    }
}
else {
    Write-Warning "mc is unavailable; MinIO objects were not backed up."
}

Get-FileHash -Algorithm SHA256 $databaseFile |
    Format-List |
    Out-File (Join-Path $resolvedDestination "checksums.txt")
Write-Host "Backup completed: $resolvedDestination"

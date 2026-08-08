param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,
    [switch]$ConfirmRestore,
    [string]$MinioAlias = "eap",
    [string]$MinioBucket = "enterprise-ai"
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore changes persistent data. Re-run with -ConfirmRestore."
}
$resolvedSource = [System.IO.Path]::GetFullPath($Source)
$databaseFile = Join-Path $resolvedSource "postgres.dump"
if (-not (Test-Path -LiteralPath $databaseFile)) {
    throw "postgres.dump was not found in the backup directory."
}
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
    throw "pg_restore is not available on PATH."
}

& pg_restore --clean --if-exists --no-owner --dbname=$DatabaseUrl $databaseFile
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL restore failed."
}

$minioDirectory = Join-Path $resolvedSource "minio"
if (Test-Path -LiteralPath $minioDirectory) {
    if (-not (Get-Command mc -ErrorAction SilentlyContinue)) {
        throw "MinIO backup exists but mc is unavailable."
    }
    & mc mirror --overwrite $minioDirectory "$MinioAlias/$MinioBucket"
    if ($LASTEXITCODE -ne 0) {
        throw "MinIO restore failed."
    }
}
Write-Host "Restore completed from: $resolvedSource"

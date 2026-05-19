param(
    [string]$CertPath = "runtime\trusted-ca\dashboard-ca.crt",
    [switch]$Machine
)

$ErrorActionPreference = "Stop"
$resolved = Resolve-Path -LiteralPath $CertPath
$target = if ($Machine) { "LocalMachine" } else { "CurrentUser" }

if ($Machine) {
    certutil -addstore $store $resolved
} else {
    certutil -user -addstore $store $resolved
}

Write-Host "Installed dashboard CA into the $target Trusted Root store: $resolved"

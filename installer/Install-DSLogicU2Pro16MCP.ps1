[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$Home
)

$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$server = Join-Path $appRoot "dslogic-mcp.exe"

if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
    throw "dslogic-mcp.exe was not found next to this installer."
}

$arguments = if ($Uninstall) {
    @("--uninstall", "--targets", "all")
} else {
    @(
        "--install",
        "--targets", "all",
        "--app-root", $appRoot,
        "--executable", $server
    )
}

if ($Home) {
    $arguments += @("--home", $Home)
}

& $server @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($Uninstall) {
    Write-Host "MCP registrations removed. The portable application and captures were kept at $appRoot." -ForegroundColor Yellow
} else {
    Write-Host "Installed. Restart Claude Code, ZCode, Codex, or another MCP host." -ForegroundColor Green
}

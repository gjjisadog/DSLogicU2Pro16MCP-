[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distRoot = Join-Path $repoRoot "dist"
$stagingRoot = Join-Path $distRoot "_staging"

if (-not $Version) {
    $projectText = Get-Content -Raw (Join-Path $repoRoot "pyproject.toml")
    $versionMatch = [regex]::Match($projectText, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $versionMatch.Success) {
        throw "Version was not supplied and could not be read from pyproject.toml."
    }
    $Version = $versionMatch.Groups[1].Value
}

$releaseName = "DSLogicU2Pro16MCP-v$Version-windows-x64"
$releaseDir = Join-Path $distRoot $releaseName
$portableDir = Join-Path $stagingRoot "portable"
$pyDistDir = Join-Path $stagingRoot "pyinstaller-dist"
$pyBuildDir = Join-Path $stagingRoot "pyinstaller-build"
$pySpecDir = Join-Path $stagingRoot "pyinstaller-spec"
$payloadZip = Join-Path $stagingRoot "payload.zip"
$versionRuntimeHook = Join-Path $stagingRoot "version_runtime_hook.py"

if ($Clean -and (Test-Path -LiteralPath $distRoot)) {
    Remove-Item -LiteralPath $distRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $releaseDir, $stagingRoot | Out-Null
if (Test-Path -LiteralPath $portableDir) {
    Remove-Item -LiteralPath $portableDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $portableDir | Out-Null

Write-Host "[1/6] Building the embedded Python MCP executable..." -ForegroundColor Cyan
@(
    "import os",
    "os.environ.setdefault('DSLOGIC_VERSION', '$Version')"
) | Set-Content -LiteralPath $versionRuntimeHook -Encoding ASCII
$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onedir", "--console",
    "--name", "dslogic-mcp",
    "--distpath", $pyDistDir,
    "--workpath", $pyBuildDir,
    "--specpath", $pySpecDir,
    "--collect-data", "mcp",
    "--collect-submodules", "mcp.server",
    "--collect-all", "anyio",
    "--collect-all", "pydantic",
    "--runtime-hook", $versionRuntimeHook,
    "--hidden-import", "mcp.server.mcpserver",
    "--hidden-import", "mcp.server.stdio",
    "--hidden-import", "mcp.server.streamable_http",
    (Join-Path $repoRoot "mcp_server\server.py")
)
& python @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Write-Host "[2/6] Assembling the offline portable bundle..." -ForegroundColor Cyan
$builtAppDir = Join-Path $pyDistDir "dslogic-mcp"
if (-not (Test-Path -LiteralPath (Join-Path $builtAppDir "dslogic-mcp.exe"))) {
    throw "PyInstaller output dslogic-mcp.exe was not found."
}
Copy-Item -Path (Join-Path $builtAppDir "*") -Destination $portableDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "runtime") -Destination (Join-Path $portableDir "runtime") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $portableDir "captures") | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot "README.md") -Destination (Join-Path $portableDir "README.md") -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "installer\Install-DSLogicU2Pro16MCP.ps1") -Destination (Join-Path $portableDir "Install-DSLogicU2Pro16MCP.ps1") -Force

Write-Host "[3/6] Adding package metadata and portable health check..." -ForegroundColor Cyan
$metadata = [ordered]@{
    name = "DSLogic U2Pro16 MCP"
    version = $Version
    server_name = "dslogic-u2pro16"
    platform = "windows-x64"
    transport = @("stdio", "streamable-http", "sse")
    offline = $true
    hardware_driver = "WinUSB (install separately if not already present)"
}
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $portableDir "manifest.json") -Encoding UTF8
$portableServer = Join-Path $portableDir "dslogic-mcp.exe"
& $portableServer --check
if ($LASTEXITCODE -ne 0) {
    throw "Portable health check failed."
}

Write-Host "[4/6] Creating the embedded installation payload..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $payloadZip) {
    Remove-Item -LiteralPath $payloadZip -Force
}
Compress-Archive -Path (Join-Path $portableDir "*") -DestinationPath $payloadZip -CompressionLevel Optimal

Write-Host "[5/6] Building the self-contained one-click installer..." -ForegroundColor Cyan
$resourceFile = Join-Path $stagingRoot "payload.rc"
$resourceObject = Join-Path $stagingRoot "payload.res"
$resourcePayloadPath = $payloadZip.Replace('\', '/')
$resourceHeaderPath = (Join-Path $repoRoot "installer\resource.h").Replace('\', '/')
@("#include `"$resourceHeaderPath`"", "IDR_PAYLOAD RCDATA `"$resourcePayloadPath`"") |
    Set-Content -LiteralPath $resourceFile -Encoding ASCII
$setupOutputDir = Join-Path $stagingRoot "setup"
if (Test-Path -LiteralPath $setupOutputDir) {
    Remove-Item -LiteralPath $setupOutputDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $setupOutputDir | Out-Null
$setupExe = Join-Path $setupOutputDir "DSLogicU2Pro16MCP-Setup.exe"
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$vcVarsCandidates = @(
    (Join-Path $programFilesX86 "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path $programFilesX86 "Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path $programFilesX86 "Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path $programFilesX86 "Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat")
)
$vcVars = $vcVarsCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $vcVars) {
    $vsWhere = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vsWhere) {
        $installationPath = (& $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1).Trim()
        if ($installationPath) {
            $candidate = Join-Path $installationPath "VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path -LiteralPath $candidate) {
                $vcVars = $candidate
            }
        }
    }
}
if (-not $vcVars) {
    throw "MSVC x64 environment script was not found. Install Visual Studio C++ build tools."
}
$compileCommand = "call `"$vcVars`" && rc.exe /nologo /fo `"$resourceObject`" `"$resourceFile`" && cl.exe /nologo /std:c++17 /EHsc /MT /O2 /DUNICODE /D_UNICODE /I`"$(Join-Path $repoRoot 'installer')`" /Fe:`"$setupExe`" `"$(Join-Path $repoRoot 'installer\Installer.cpp')`" `"$resourceObject`" /link /SUBSYSTEM:CONSOLE"
& cmd.exe /d /s /c $compileCommand
if ($LASTEXITCODE -ne 0) {
    throw "Native installer compilation failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $setupExe)) {
    throw "Self-contained setup executable was not produced."
}

Write-Host "[6/6] Writing release archives and checksums..." -ForegroundColor Cyan
$portableZip = Join-Path $releaseDir "$releaseName-portable.zip"
Compress-Archive -Path (Join-Path $portableDir "*") -DestinationPath $portableZip -CompressionLevel Optimal
$setupRelease = Join-Path $releaseDir "$releaseName-Setup.exe"
Copy-Item -LiteralPath $setupExe -Destination $setupRelease -Force
$checksums = @(
    (Get-FileHash -Algorithm SHA256 -LiteralPath $setupRelease),
    (Get-FileHash -Algorithm SHA256 -LiteralPath $portableZip)
) | ForEach-Object { "$($_.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($_.Path))" }
$checksums | Set-Content -LiteralPath (Join-Path $releaseDir "SHA256SUMS.txt") -Encoding ASCII

Write-Host "Offline package ready:" -ForegroundColor Green
Write-Host "  $setupRelease"
Write-Host "  $portableZip"
Write-Host "  $(Join-Path $releaseDir 'SHA256SUMS.txt')"

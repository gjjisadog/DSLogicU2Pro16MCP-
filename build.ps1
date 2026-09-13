# Build script for DSLogic U2Pro16 Native CLI on Windows
Continue = "Stop"

Write-Host "[1/3] Configuring CMake build..." -ForegroundColor Cyan
cmake -B build -G "MinGW Makefiles" -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++

Write-Host "[2/3] Building dslogic_cli binary..." -ForegroundColor Cyan
cmake --build build --config Release

Write-Host "[3/3] Checking runtime files..." -ForegroundColor Cyan
if (Test-Path "runtime/dslogic_cli.exe") {
    Write-Host "Build complete! runtime/dslogic_cli.exe is ready." -ForegroundColor Green
} else {
    Write-Error "Build failed: runtime/dslogic_cli.exe not found."
}

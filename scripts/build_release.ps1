param(
    [string]$PythonExe = "",
    [string]$AppName = "FlowArchitect"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
$defaultPython = Join-Path $PSScriptRoot "..\..\FlowArchitect\.venv\Scripts\python.exe"

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = $defaultPython
}

$PythonExe = [System.IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$distRoot = Join-Path $repoRoot "dist_release"
$buildRoot = Join-Path $repoRoot "build_release"
$entryPoint = Join-Path $repoRoot "src\main.py"
$appDir = Join-Path $distRoot $AppName
$configOut = Join-Path $appDir "config"
$dataOut = Join-Path $appDir "data"

Write-Host "Python: $PythonExe"
Write-Host "Repo  : $repoRoot"

if (Test-Path $buildRoot) {
    Remove-Item $buildRoot -Recurse -Force
}
if (Test-Path $distRoot) {
    Remove-Item $distRoot -Recurse -Force
}

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $AppName `
    --specpath $buildRoot `
    --workpath (Join-Path $buildRoot "work") `
    --distpath $distRoot `
    --paths $repoRoot `
    $entryPoint

New-Item -ItemType Directory -Force -Path $configOut | Out-Null
New-Item -ItemType Directory -Force -Path $dataOut | Out-Null

Copy-Item (Join-Path $repoRoot "config\settings.json") $configOut -Force
Copy-Item (Join-Path $repoRoot "config\PIM_structure.yaml") $configOut -Force
Copy-Item (Join-Path $repoRoot "config\prompts") $configOut -Recurse -Force

Get-ChildItem $configOut -Recurse -Include "flowarchitect.db*", "*.log" | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Release build is ready:"
Write-Host "  EXE    : $(Join-Path $appDir "$AppName.exe")"
Write-Host "  Config : $configOut"
Write-Host "  Data   : $dataOut"

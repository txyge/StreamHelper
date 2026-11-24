param(
    [string]$Python = "python",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "dist"),
    [string]$BuildDirectory = (Join-Path $PSScriptRoot "build")
)

$ErrorActionPreference = "Stop"
$destination = [IO.Path]::GetFullPath($OutputDirectory)
$scratch = [IO.Path]::GetFullPath($BuildDirectory)
Push-Location $PSScriptRoot
try {
    & $Python -m PyInstaller --noconfirm --onefile --console --noupx `
        --name StreamHelper --distpath $destination --workpath (Join-Path $scratch "pyinstaller") --specpath $scratch `
        --icon "$PSScriptRoot/web/favicon.ico" --add-data "$PSScriptRoot/web:web" --add-data "$PSScriptRoot/schema.sql:." "$PSScriptRoot/app.py"
    if ($LASTEXITCODE) { throw "PyInstaller build failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}

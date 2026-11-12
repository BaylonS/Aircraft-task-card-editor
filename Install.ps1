$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { & $python.Source -3 -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10 or newer with Tcl/Tk from python.org, then retry.' }
}
& './.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'Aircraft Task Card Editor.lnk'))
$link.TargetPath = Join-Path $PSScriptRoot 'Launch.cmd'
$link.WorkingDirectory = $PSScriptRoot
$link.Description = 'Add tail numbers and task descriptions to PDF task-card headers'
$link.Save()
Write-Host 'Installed. Open Aircraft Task Card Editor on your desktop.'

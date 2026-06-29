$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$shortcutPath = Join-Path $projectDir 'AIRT.lnk'
$targetPath = Join-Path $projectDir 'AIRT.bat'
$iconPath = Join-Path $projectDir 'assets\airt-icon.ico'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $projectDir
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath"

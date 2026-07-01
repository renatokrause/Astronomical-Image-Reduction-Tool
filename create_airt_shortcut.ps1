$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$shortcutPath = Join-Path $projectDir 'AIRT.lnk'
$targetPath = Join-Path $projectDir 'AIRT.bat'
$iconPath = Join-Path $projectDir 'src\airt\resources\icons\app.ico'

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $projectDir

if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}

$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath"

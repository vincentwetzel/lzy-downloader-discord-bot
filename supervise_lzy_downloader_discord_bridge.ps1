$ErrorActionPreference = 'SilentlyContinue'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridgeScript = Join-Path $scriptDirectory 'lzy_downloader_discord_bridge.py'
$stopMarker = Join-Path $scriptDirectory 'lzy_downloader_discord_bridge.stop'

while (-not (Test-Path -LiteralPath $stopMarker)) {
    $bridge = Start-Process -FilePath 'pythonw.exe' `
        -ArgumentList @($bridgeScript) `
        -WorkingDirectory $scriptDirectory `
        -WindowStyle Hidden `
        -PassThru

    $bridge.WaitForExit()

    if (Test-Path -LiteralPath $stopMarker) {
        break
    }

    Start-Sleep -Seconds 10
}

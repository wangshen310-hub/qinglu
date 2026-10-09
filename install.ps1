param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\QingLu'),
    [switch]$NoShortcut,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Program" }
}

function Find-Python {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\QingLuPython314\python.exe')
    )
    foreach ($key in @('HKCU:\Software\Python\PythonCore\3.14\InstallPath', 'HKLM:\Software\Python\PythonCore\3.14\InstallPath')) {
        if (Test-Path -LiteralPath $key) {
            $location = (Get-Item -LiteralPath $key).GetValue('')
            if ($location) { $candidates += Join-Path $location 'python.exe' }
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates += $command.Source }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate) {
            $version = & $candidate -c 'import sys,struct;print(sys.version_info.major,sys.version_info.minor,struct.calcsize(chr(80))*8)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -eq '3 14 64') { return $candidate }
        }
    }
    return $null
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'QingLu requires 64-bit Windows.' }
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This installer currently supports Windows x64 only.' }
    $source = $PSScriptRoot
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    Write-Host '[1/4] Preparing Python 3.14 (64-bit)...'
    $python = Find-Python
    if (-not $python) {
        # Use a current stable patch release from python.org, never a third-party mirror.
        $index = (Invoke-WebRequest 'https://www.python.org/ftp/python/' -UseBasicParsing).Content
        $versions = [regex]::Matches($index, 'href="(3\.14\.\d+)/"') | ForEach-Object { [version]$_.Groups[1].Value }
        $downloadUrl = $null
        foreach ($release in ($versions | Sort-Object -Descending -Unique)) {
            $candidateUrl = "https://www.python.org/ftp/python/$release/python-$release-amd64.exe"
            try {
                $null = Invoke-WebRequest $candidateUrl -Method Head -UseBasicParsing
                $downloadUrl = $candidateUrl
                break
            } catch {
                if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { continue }
                throw
            }
        }
        if (-not $downloadUrl) { throw 'No stable Python 3.14 Windows installer was found.' }
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('qinglu-python-' + [guid]::NewGuid().ToString('N') + '.exe')
        Invoke-WebRequest $downloadUrl -OutFile $installer -UseBasicParsing
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'Python installer signature could not be verified. Installation stopped.'
        }
        $pythonDir = Join-Path $env:LOCALAPPDATA 'Programs\QingLuPython314'
        $process = Start-Process -FilePath $installer -ArgumentList @('/quiet','InstallAllUsers=0','Include_launcher=0','Include_test=0','Include_pip=1','Include_tcltk=1','PrependPath=0',('TargetDir="' + $pythonDir + '"')) -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -notin @(0,3010)) { throw "Python installation failed: $($process.ExitCode)" }
        $python = Find-Python
        if (-not $python) { throw 'Python installation needs attention. Restart Windows and try again.' }
    }
    Write-Host '[2/4] Installing QingLu for the current user...'
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $files = @('recorder.py','recorder_ui.py','recorder_tray.py','audio_inputs.py','audio_timeline.py','window_capture.py','requirements-lock.txt','LICENSE','README.md','THIRD_PARTY.md')
    # The launcher has a Unicode filename; discover it without depending on console encoding.
    $launchers = @(Get-ChildItem -LiteralPath $source -Filter '*.pyw' -File)
    if ($launchers.Count -ne 1) { throw 'Extract the complete release ZIP before running the installer.' }
    if ($source.TrimEnd('\') -ne $InstallDir.TrimEnd('\')) {
        foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $source $file) -Destination $InstallDir -Force }
        Copy-Item -LiteralPath $launchers[0].FullName -Destination $InstallDir -Force
        $assetDir = Join-Path $InstallDir 'assets'
        New-Item -ItemType Directory -Path $assetDir -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $source 'assets\qinglu.ico') -Destination $assetDir -Force
        Copy-Item -LiteralPath (Join-Path $source 'assets\qinglu-icon.png') -Destination $assetDir -Force
    }
    $venv = Join-Path $InstallDir '.venv'
    Invoke-Checked $python @('-m','venv',$venv)
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    Write-Host '[3/4] Installing application dependencies (internet required)...'
    Invoke-Checked $venvPython @('-m','pip','install','--disable-pip-version-check','-r',(Join-Path $InstallDir 'requirements-lock.txt'))
    Invoke-Checked $venvPython @('-c','import tkinter,PIL,numpy,cv2,imageio_ffmpeg,pyaudiowpatch,windows_capture; print(''Dependencies ready'')')
    $pythonw = Join-Path $venv 'Scripts\pythonw.exe'
    $launcher = Join-Path $InstallDir $launchers[0].Name
    Write-Host '[4/4] Creating desktop shortcut...'
    if (-not $NoShortcut) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'QingLu.lnk'))
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = '"' + $launcher + '"'
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.IconLocation = Join-Path $InstallDir 'assets\qinglu.ico'
        $shortcut.Save()
    }
    Write-Host "QingLu installed successfully: $InstallDir" -ForegroundColor Green
    if (-not $NoLaunch) { Start-Process -FilePath $pythonw -ArgumentList ('"' + $launcher + '"') -WorkingDirectory $InstallDir }
} catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

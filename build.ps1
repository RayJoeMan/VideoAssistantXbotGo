# Builds the Lacrosse Highlight Assistant on Windows.
# Usage:
#   .\build.ps1                        # onedir bundle (fast startup)
#   .\build.ps1 -OneFile               # single-file executable
#   .\build.ps1 -BundleFFmpeg          # bundle ffmpeg/ffprobe into the app
#   .\build.ps1 -Smoke                 # build, then verify it launches
param(
    [switch]$OneFile,
    [switch]$BundleFFmpeg,
    [switch]$Smoke
)
$ErrorActionPreference = "Stop"

$scriptArgs = @()
if ($OneFile) { $scriptArgs += "--onefile" }
if ($BundleFFmpeg) { $scriptArgs += "--bundle-ffmpeg" }
if ($Smoke) { $scriptArgs += "--smoke" }

python scripts/build.py @scriptArgs
exit $LASTEXITCODE

# SDL2 runtime only: no SDK or import library is required by the pad backend.
# Official archive and SHA256 are pinned rather than following latest releases.
$script:TjSdlArchiveSha256 = '6cf9706eefd0a4a06dc764007934d428afaf029fabdd408a9e646048c91e18fb'
$script:TjSdlArchiveUrl = 'https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10-win32-x64.zip'
$script:TjSdlLicense = Join-Path (Split-Path $PSScriptRoot) 'licenses\SDL2.txt'

function Assert-TjSdlArchive {
    param([Parameter(Mandatory=$true)][string]$Archive,
          [string]$ExpectedSha256 = $script:TjSdlArchiveSha256)
    # .NET avoids PowerShell module-discovery differences between PS5 and PS7.
    $stream = [IO.File]::OpenRead($Archive)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $sha.Dispose(); $stream.Dispose() }
    if ($actual -ne $ExpectedSha256) {
        throw 'SDL2 archive SHA256 mismatch; refusing to install it.'
    }
}

function Copy-TjSdlRuntime {
    param([Parameter(Mandatory=$true)][string]$Archive,
          [Parameter(Mandatory=$true)][string]$CacheDirectory,
          [Parameter(Mandatory=$true)][string]$Destination,
          [string]$ExpectedSha256 = $script:TjSdlArchiveSha256)
    Assert-TjSdlArchive -Archive $Archive -ExpectedSha256 $ExpectedSha256
    $unpacked = Join-Path $CacheDirectory 'unpacked'
    Expand-Archive -LiteralPath $Archive -DestinationPath $unpacked -Force -ErrorAction Stop
    $dll = Join-Path $unpacked 'SDL2.dll'
    $readme = Join-Path $unpacked 'README-SDL.txt'
    foreach ($required in @($dll, $readme, $script:TjSdlLicense)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "SDL2 required file missing: $required" }
    }
    New-Item -ItemType Directory -Force -Path $Destination -ErrorAction Stop | Out-Null
    Copy-Item -LiteralPath $dll -Destination $Destination -Force -ErrorAction Stop
    Copy-Item -LiteralPath $readme -Destination $Destination -Force -ErrorAction Stop
    Copy-Item -LiteralPath $script:TjSdlLicense -Destination (Join-Path $Destination 'SDL2-LICENSE.txt') -Force -ErrorAction Stop
}

function Install-TjSdlRuntime {
    param([Parameter(Mandatory=$true)][string]$CacheDirectory,
          [Parameter(Mandatory=$true)][string]$Destination)
    New-Item -ItemType Directory -Force -Path $CacheDirectory -ErrorAction Stop | Out-Null
    $archive = Join-Path $CacheDirectory 'SDL2-2.32.10-win32-x64.zip'
    if (-not (Test-Path -LiteralPath $archive)) {
        $download = "$archive.download"
        Invoke-WebRequest -UseBasicParsing -Uri $script:TjSdlArchiveUrl -OutFile $download -ErrorAction Stop
        Assert-TjSdlArchive -Archive $download
        Move-Item -LiteralPath $download -Destination $archive -Force -ErrorAction Stop
    }
    Copy-TjSdlRuntime -Archive $archive -CacheDirectory $CacheDirectory -Destination $Destination
}

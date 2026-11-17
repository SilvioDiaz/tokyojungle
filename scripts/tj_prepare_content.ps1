# Local package/DLC preparation. Author: matymeatboy. No game data distributed.
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [string[]]$Packages = @(),
    [string]$Licenses = '',
    [string]$Rpcs3 = ''
)
$ErrorActionPreference = 'Stop'
try {
    $Root = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw 'Installation root does not exist' }
    $ini = Join-Path $Root 'launcher.ini'
    Add-Type @'
using System.Runtime.InteropServices;
using System.Text;
public static class TjContentIni {
 [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
 public static extern bool WritePrivateProfileString(string section,string key,string value,string file);
 [DllImport("kernel32", CharSet=CharSet.Unicode)]
 public static extern uint GetPrivateProfileString(string section,string key,string value,StringBuilder result,uint size,string file);
}
'@
    if (-not $Rpcs3) { $Rpcs3 = $env:TJ_RPCS3 }
    if (-not $Rpcs3) {
        $value = New-Object Text.StringBuilder 32768
        [void][TjContentIni]::GetPrivateProfileString('paths','rpcs3','',$value,32768,$ini)
        $Rpcs3 = $value.ToString()
    }
    if (-not $Rpcs3) {
        foreach ($candidate in @((Join-Path $Root '.build\rpcs3\rpcs3.exe'), 'C:\Emulator\PS3\rpcs3.exe', "$env:ProgramFiles\RPCS3\rpcs3.exe")) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $Rpcs3 = $candidate; break }
        }
    }
    if (-not $Rpcs3 -or -not (Test-Path -LiteralPath $Rpcs3 -PathType Leaf)) {
        throw 'RPCS3 not found: pass -Rpcs3 or set [paths] rpcs3= in launcher.ini. It is used offline for decryption only.'
    }
    $python = $env:TJ_PYTHON
    $prefix = @()
    if (-not $python) {
        $command = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($command) { $python = $command.Source; $prefix = @('-3') }
        else {
            $command = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($command) { $python = $command.Source }
        }
    }
    if (-not $python) { throw 'Python 3 is required. Run BUILD.bat first.' }
    $arguments = @((Join-Path $PSScriptRoot 'lajungla_setup.py'), '--root', (Join-Path $Root 'content'), '--rpcs3', $Rpcs3,
                   '--elf-output', (Join-Path $Root 'engine\input\EBOOT.ELF'))
    if ($Licenses) { $arguments += @('--licenses', $Licenses) }
    foreach ($package in $Packages) { $arguments += @('--package', $package) }
    & $python @prefix @arguments
    if ($LASTEXITCODE) { throw "Content preparation failed ($LASTEXITCODE); previous mounted content and saves were preserved" }
    if (-not [TjContentIni]::WritePrivateProfileString('paths','game',(Join-Path $Root 'content\mounted'),$ini)) {
        throw 'Content prepared but launcher.ini could not be updated'
    }
    [void][TjContentIni]::WritePrivateProfileString('paths','rpcs3',$Rpcs3,$ini)
    Write-Output 'Game/DLC content prepared. Existing engine/savedata was not modified.'
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}

# Synthetic cached-input regression. Author: matymeatboy.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\scripts\tj_build_all.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Build script does not parse' }
$fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-ExpectedElf' }, $true)
if (-not $fn) { throw 'Missing cached ELF validator' }
Invoke-Expression $fn.Extent.Text
function Fail($message) { throw "VALIDATION: $message" }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('tj-elf-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
$elf = Join-Path $temp 'cached input.ELF'
try {
    [IO.File]::WriteAllBytes($elf, [byte[]](0,1,2,3))
    $hash = (Get-FileHash -LiteralPath $elf -Algorithm SHA256).Hash
    Assert-ExpectedElf $elf $hash
    foreach ($entry in @(@($elf, ('0' * 64)), @((Join-Path $temp 'missing.ELF'), $hash), @($temp, $hash))) {
        $failed = $false
        try { Assert-ExpectedElf $entry[0] $entry[1] } catch { $failed = $_.Exception.Message.StartsWith('VALIDATION:') }
        if (-not $failed) { throw 'Invalid input accepted' }
    }
    # The guard must run even when decryption and recompilation are skipped.
    $calls = @($ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.PipelineAst] -and $_.PipelineElements[0] -is [System.Management.Automation.Language.CommandAst] -and $_.PipelineElements[0].GetCommandName() -eq 'Assert-ExpectedElf' })
    if ($calls.Count -ne 1) { throw 'Cached ELF validation must be unconditional at script scope' }
    Write-Output 'ELF validation: valid, mismatch, missing, directory and cached-path guard passed'
} finally {
    if (Test-Path -LiteralPath $elf) { Remove-Item -LiteralPath $elf }
    Remove-Item -LiteralPath $temp
}

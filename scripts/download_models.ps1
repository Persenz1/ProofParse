[CmdletBinding()]
param(
    [ValidateSet('all', 'first-batch')]
    [string]$Group = 'all',
    [string]$Models = '',
    [string]$CacheDir = 'D:\DevTools\Models\huggingface\hub',
    [int]$Workers = 2,
    [string]$PythonExe = 'D:\DevTools\Conda\envs\litparse\python.exe',
    [switch]$List
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'download_models.py'
$downloadArgs = @(
    $scriptPath,
    '--group', $Group,
    '--cache-dir', $CacheDir,
    '--workers', $Workers.ToString()
)
if ($Models) {
    $downloadArgs += '--models'
    $downloadArgs += ($Models -split ',')
}
if ($List) {
    $downloadArgs += '--list'
}

& $PythonExe @downloadArgs
exit $LASTEXITCODE

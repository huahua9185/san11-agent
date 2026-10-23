param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ReaArguments)
$ErrorActionPreference = 'Stop'
$researchRoot = Join-Path (Split-Path $PSScriptRoot -Parent) '.rea-tools'
$ghidraRoot = Join-Path $researchRoot 'ghidra_12.1.4_PUBLIC'
$jdkRoot = Join-Path $researchRoot 'jdk-21.0.12.1+1'
if (-not (Test-Path -LiteralPath (Join-Path $ghidraRoot 'support\analyzeHeadless.bat'))) { throw 'Portable Ghidra is not extracted' }
if (-not (Test-Path -LiteralPath (Join-Path $jdkRoot 'bin\java.exe'))) { throw 'Portable JDK is not extracted' }
$previousGhidra = $env:GHIDRA_INSTALL_DIR
$previousJava = $env:JAVA_HOME
$previousProvider = $env:REA_ANALYSIS_PROVIDER
$previousPath = $env:PATH
try {
    $env:GHIDRA_INSTALL_DIR = $ghidraRoot
    $env:JAVA_HOME = $jdkRoot
    $env:REA_ANALYSIS_PROVIDER = 'ghidra'
    $env:PATH = (Join-Path $jdkRoot 'bin') + ';' + $env:PATH
    & rea @ReaArguments
    if ($LASTEXITCODE -ne 0) { throw "REA exited with code $LASTEXITCODE" }
} finally {
    $env:GHIDRA_INSTALL_DIR = $previousGhidra
    $env:JAVA_HOME = $previousJava
    $env:REA_ANALYSIS_PROVIDER = $previousProvider
    $env:PATH = $previousPath
}

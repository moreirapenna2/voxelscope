param([string[]]$Tasks = @('build'))
$ErrorActionPreference = 'Stop'
# Use JAVA_HOME or Java 21 found by Gradle. No launcher-specific paths.
Push-Location $PSScriptRoot
try {
    & .\gradlew.bat @Tasks --console=plain
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }

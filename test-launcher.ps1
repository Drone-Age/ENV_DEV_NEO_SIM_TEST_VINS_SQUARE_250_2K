[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'launcher-contract.psm1') -Force

function Assert-Equal($Expected, $Actual, [string]$Message) {
    if ($Expected -ne $Actual) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

Assert-Equal 'headless' (Get-QualificationVisualMode) 'Default mode must be headless.'
Assert-Equal 'headless' (Get-QualificationVisualMode -Headless) 'Explicit headless must remain compatible.'
Assert-Equal 'visual' (Get-QualificationVisualMode -VisualUi) 'VisualUi must opt into the GUI.'

$conflictRejected = $false
try { Get-QualificationVisualMode -VisualUi -Headless | Out-Null }
catch { $conflictRejected = $true }
Assert-Equal $true $conflictRejected 'Conflicting visual switches must be rejected.'

$explicit = @(Get-QualificationDistroCandidates -ExplicitDistro 'Custom-QUAL' -EnvironmentDistro 'Ignored')
Assert-Equal 1 $explicit.Count 'An explicit distro must be the only candidate.'
Assert-Equal 'Custom-QUAL' $explicit[0] 'Explicit distro order is incorrect.'

$automatic = @(Get-QualificationDistroCandidates -EnvironmentDistro 'Preferred-QUAL')
Assert-Equal 'Preferred-QUAL' $automatic[0] 'Environment distro must be first.'
Assert-Equal 'ENV-NEO-SIM1-QUAL' $automatic[1] 'Qualification distro must be second.'
Assert-Equal 'Ubuntu' $automatic[2] 'Ubuntu must be the verified fallback only.'

$startup = '[env-neo] ERROR: Gazebo exited before becoming ready; camera topic did not appear.'
Assert-Equal $true (Test-PreArmStartupFailure -ExitCode 1 -Transcript $startup) 'Proven pre-ARM startup failure must be retryable.'
Assert-Equal $false (Test-PreArmStartupFailure -ExitCode 1 -Transcript $startup -RunEvidence 'mission_stage=ARMED') 'No retry is allowed after ARM.'
Assert-Equal $false (Test-PreArmStartupFailure -ExitCode 1 -Transcript 'qualification failed') 'Unproven failures must not be retried.'
$gatewayStartup = '[env-neo] ERROR: SIM Gateway published no status sample.'
Assert-Equal $true (Test-PreArmStartupFailure -ExitCode 1 -Transcript $gatewayStartup) 'Explicit Gateway pre-ARM status timeout must be retryable.'
Assert-Equal $false (Test-PreArmStartupFailure -ExitCode 1 -Transcript $gatewayStartup -RunEvidence '"event": "GATEWAY_LOITER_BOOTSTRAP_STARTED"') 'Gateway failure after ARM must never be retried.'

Write-Host 'OK launcher contracts'

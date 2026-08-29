Set-StrictMode -Version Latest

function Get-QualificationVisualMode {
    [CmdletBinding()]
    param(
        [switch]$VisualUi,
        [switch]$Headless
    )

    if ($VisualUi -and $Headless) {
        throw '-VisualUi and -Headless are mutually exclusive.'
    }
    if ($VisualUi) { return 'visual' }
    return 'headless'
}

function Get-QualificationDistroCandidates {
    [CmdletBinding()]
    param(
        [string]$ExplicitDistro = '',
        [string]$EnvironmentDistro = ''
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitDistro)) {
        return @($ExplicitDistro.Trim())
    }

    $ordered = @(
        $EnvironmentDistro,
        'ENV-NEO-SIM1-QUAL',
        'Ubuntu'
    )
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in $ordered) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $trimmed = $candidate.Trim()
        if (-not $result.Contains($trimmed)) { $result.Add($trimmed) }
    }
    return @($result)
}

function Test-QualificationArmObserved {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$EvidenceText = '')

    return [bool]($EvidenceText -match '(?im)mission_stage=ARMED|"event"\s*:\s*"GATEWAY_LOITER_BOOTSTRAP_STARTED"|"armed"\s*:\s*true')
}

function Test-PreArmStartupFailure {
    [CmdletBinding()]
    param(
        [int]$ExitCode,
        [AllowEmptyString()][string]$Transcript = '',
        [AllowEmptyString()][string]$RunEvidence = ''
    )

    if ($ExitCode -eq 0) { return $false }
    if (Test-QualificationArmObserved -EvidenceText ($Transcript + "`n" + $RunEvidence)) {
        return $false
    }

    $startupFailure = $Transcript -match '(?is)(Gazebo|SITL|camera|ROS bridge).{0,160}(exited before becoming ready|did not appear|did not remain alive|timed out waiting)'
    return [bool]$startupFailure
}

Export-ModuleMember -Function `
    Get-QualificationVisualMode, `
    Get-QualificationDistroCandidates, `
    Test-QualificationArmObserved, `
    Test-PreArmStartupFailure

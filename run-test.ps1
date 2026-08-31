[CmdletBinding()]
param(
    [Alias('Profile')]
    [string]$ProfilePath = '',
    [string]$Configuration = '',
    [string]$Suite = '',
    [switch]$ListConfigurations,
    [switch]$Headless,
    [switch]$VisualUi,
    [switch]$Rosbag,
    [switch]$Resume,
    [switch]$RuntimeVerified,
    [switch]$NoOpenReport,
    [switch]$PrintOnly,
    [ValidateSet('gnss', 'gps_denied')]
    [string]$NavigationMode = 'gnss',
    [ValidateSet('simulation', 'real_vehicle')]
    [string]$Backend = 'simulation',
    [string]$SiteProfile = '',
    [string]$ReferenceFile = '',
    [string]$Distro = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Import-Module (Join-Path $PSScriptRoot 'launcher-contract.psm1') -Force
$visualMode = Get-QualificationVisualMode -VisualUi:$VisualUi -Headless:$Headless
$useHeadless = $visualMode -eq 'headless'

function Resolve-VerifiedQualificationDistro {
    $candidates = @(Get-QualificationDistroCandidates `
        -ExplicitDistro $Distro `
        -EnvironmentDistro $env:ENV_NEO_QUALIFICATION_DISTRO)
    $failures = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in $candidates) {
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $verification = & powershell.exe -NoProfile -ExecutionPolicy Bypass `
                -File (Join-Path $repoRoot 'dev.ps1') verify -Distro $candidate 2>&1 | Out-String
            $verificationExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedPreference
        }
        if ($verificationExitCode -eq 0) {
            Write-Host "[VINS-POSE-GRAPH] Перевірений WSL runtime: $candidate"
            return $candidate
        }
        $failures.Add("$candidate (exit $verificationExitCode)")
    }
    throw ('Жодний WSL distro не пройшов runtime verification: ' + ($failures -join ', '))
}

function Find-ValidCompletedRun {
    param(
        [Parameter(Mandatory)][string]$ConfigurationId,
        [Parameter(Mandatory)][string]$ResolvedProfile
    )
    $expectedHash = (Get-FileHash -LiteralPath $ResolvedProfile -Algorithm SHA256).Hash.ToLowerInvariant()
    $canonicalRoot = Join-Path $PSScriptRoot 'logs'
    $matches = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path -LiteralPath $canonicalRoot -PathType Container)) { return $null }
    foreach ($reportPath in Get-ChildItem -LiteralPath $canonicalRoot -Recurse -Filter 'vins-route-report.json' -File) {
        try {
            $report = Get-Content -Raw -LiteralPath $reportPath.FullName | ConvertFrom-Json
        } catch {
            continue
        }
        if (
            [string]$report.configuration_id -eq $ConfigurationId -and
            [string]$report.profile_sha256 -eq $expectedHash -and
            [string]$report.verdict -eq 'PASS' -and
            $report.validity.passed -eq $true
        ) {
            $matches.Add([pscustomobject]@{
                RunId = [string]$report.run_id
                CompletedAt = [string]$report.completed_at_utc
                ReportPath = $reportPath.FullName
            })
        }
    }
    return $matches | Sort-Object CompletedAt | Select-Object -Last 1
}

function Convert-WslPathToWindowsPath {
    param([Parameter(Mandatory)][string]$Path)
    if ($Path -match '^/mnt/([a-zA-Z])/(.*)$') {
        return ('{0}:\{1}' -f $Matches[1].ToUpperInvariant(), $Matches[2].Replace('/', '\'))
    }
    return $Path
}

function Get-LatestEvidenceDirectory {
    $latestRunDirectoryState = Join-Path $repoRoot '.runtime\state\latest_run_dir'
    if (-not (Test-Path -LiteralPath $latestRunDirectoryState -PathType Leaf)) { return $null }
    $runtimeDirectory = Convert-WslPathToWindowsPath `
        -Path ((Get-Content -Raw -LiteralPath $latestRunDirectoryState).Trim())
    if (-not (Test-Path -LiteralPath $runtimeDirectory -PathType Container)) { return $null }
    return (Split-Path -Parent $runtimeDirectory)
}

$configurationFiles = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'configurations') -Filter '*.json' -File -Recurse -ErrorAction SilentlyContinue)
if ($ListConfigurations) {
    $profiles = @((Get-Item -LiteralPath (Join-Path $PSScriptRoot 'profile.json'))) + $configurationFiles
    foreach ($item in $profiles) {
        $candidate = Get-Content -Raw -LiteralPath $item.FullName | ConvertFrom-Json
        Write-Host ("{0}`t{1}`t{2}" -f $candidate.configuration_id, $candidate.route.mission_file, $item.FullName)
    }
    exit 0
}
if ($Suite) {
    $suitePath = if (Test-Path -LiteralPath $Suite) { (Resolve-Path -LiteralPath $Suite).Path } else { (Resolve-Path -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'suites') "$Suite.json")).Path }
    $suiteContract = Get-Content -Raw -LiteralPath $suitePath | ConvertFrom-Json
    $suiteExitCode = 0
    $suiteItems = if ($suiteContract.runs) { @($suiteContract.runs) } else { @($suiteContract.configurations) }
    $suiteDistro = if ($PrintOnly) { $Distro } else { Resolve-VerifiedQualificationDistro }
    foreach ($item in $suiteItems) {
        $itemProfile = (Resolve-Path -LiteralPath (Join-Path (Split-Path -Parent $suitePath) ([string]$item.profile))).Path
        Write-Host "[VINS-POSE-GRAPH] Набір $($suiteContract.suite_id): $($item.configuration_id)"
        if ($Resume -and -not $PrintOnly) {
            $completed = Find-ValidCompletedRun -ConfigurationId ([string]$item.configuration_id) -ResolvedProfile $itemProfile
            if ($completed) {
                Write-Host "[VINS-POSE-GRAPH] Resume: пропущено валідний PASS run $($completed.RunId) із точним profile SHA-256."
                continue
            }
        }
        & $PSCommandPath -ProfilePath $itemProfile -Headless:$Headless -VisualUi:$VisualUi -Rosbag:$Rosbag -NoOpenReport -PrintOnly:$PrintOnly -NavigationMode $NavigationMode -Backend $Backend -SiteProfile $SiteProfile -ReferenceFile $ReferenceFile -Distro $suiteDistro -RuntimeVerified:(-not $PrintOnly -and $Backend -eq 'simulation')
        if ($LASTEXITCODE -ne 0) {
            $suiteExitCode = $LASTEXITCODE
            if (-not $suiteContract.continue_on_fail) { break }
        }
    }
    if (-not $PrintOnly) {
        $consolidator = if ($suiteContract.consolidator) {
            [string]$suiteContract.consolidator
        } elseif ($suiteContract.runs) {
            'consolidate_pose_graph_campaign.py'
        } else {
            'consolidate_pose_graph_smoke.py'
        }
        & python (Join-Path $PSScriptRoot $consolidator) --suite $suitePath
        if ($LASTEXITCODE -ne 0 -and $suiteExitCode -eq 0) { $suiteExitCode = $LASTEXITCODE }
    }
    exit $suiteExitCode
}
if ($Configuration) {
    $matchedProfile = @((Get-Item -LiteralPath (Join-Path $PSScriptRoot 'profile.json'))) + $configurationFiles | Where-Object {
        (Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json).configuration_id -eq $Configuration
    } | Select-Object -First 1
    if (-not $matchedProfile) { throw "Unknown configuration: $Configuration. Use -ListConfigurations." }
    $ProfilePath = $matchedProfile.FullName
}
$ProfilePath = if ($ProfilePath) { $ProfilePath } else { Join-Path $PSScriptRoot 'profile.json' }
$resolvedProfilePath = (Resolve-Path -LiteralPath $ProfilePath).Path
$profileConfig = Get-Content -Raw -LiteralPath $resolvedProfilePath | ConvertFrom-Json
$backendArgs = @('--profile', $resolvedProfilePath, '--backend', $Backend)
if ($SiteProfile) { $backendArgs += @('--site-profile', (Resolve-Path -LiteralPath $SiteProfile).Path) }
if ($ReferenceFile) { $backendArgs += @('--reference-file', (Resolve-Path -LiteralPath $ReferenceFile).Path) }
& python (Join-Path $PSScriptRoot 'backend_contract.py') @backendArgs
if ($LASTEXITCODE -ne 0) { throw "Backend contract не пройдено для $Backend." }
$version = (Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'VERSION')).Trim()
$contract = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'test-contract.json') | ConvertFrom-Json
if ($profileConfig.test_version -ne $version -or $contract.version -ne $version) { throw 'Версії VERSION/profile/contract не збігаються.' }
$expectedSourceSet = if ($NavigationMode -eq 'gps_denied') { 2 } else { 1 }
if ([int]$profileConfig.navigation.flight_source_set -ne $expectedSourceSet) {
    throw "NavigationMode $NavigationMode не відповідає підписаному flight_source_set $($profileConfig.navigation.flight_source_set)."
}
if ($NavigationMode -eq 'gnss') {
    if ($profileConfig.navigation.ekf_switch_allowed -ne $false -or $profileConfig.navigation.control_source -ne 'GNSS') {
        throw 'GNSS-тест має залишатися на Source Set 1 без перемикання EKF.'
    }
} else {
    if (
        $profileConfig.navigation.ekf_switch_allowed -ne $true -or
        $profileConfig.navigation.control_source -ne 'VINS_ExternalNav' -or
        $profileConfig.navigation.vins_role -ne 'flight_control_external_nav' -or
        $profileConfig.navigation.gnss_fusion_during_route_allowed -ne $false -or
        $profileConfig.navigation.source_set_fallback_after_route_start_allowed -ne $false
    ) { throw 'GPS-denied profile не містить повний fail-closed ExternalNav контракт.' }
}
if ($profileConfig.execution.architecture_contract_checks -ne $false) { throw 'Architecture checks не входять до цього on-demand тесту.' }
$mission = Join-Path (Split-Path -Parent $resolvedProfilePath) ([string]$profileConfig.route.mission_file)
if (-not (Test-Path -LiteralPath $mission -PathType Leaf)) { throw "Файл місії не знайдено: $mission" }
$relativeProfile = $resolvedProfilePath.Substring($repoRoot.TrimEnd('\').Length + 1).Replace('\', '/')

Write-Host "[VINS-SQUARE-2K] Тест: $($profileConfig.test_id) v$version"
Write-Host "[VINS-SQUARE-2K] Конфігурація: $($profileConfig.configuration_id)"
Write-Host "[VINS-SQUARE-2K] Backend: $Backend"
if ($NavigationMode -eq 'gps_denied') {
    Write-Host '[VINS-POSE-GRAPH] Керування маршрутом: VINS ExternalNav / EKF Source Set 2; GNSS fusion і fallback заборонені.'
} else {
    Write-Host '[VINS-POSE-GRAPH] Керування польотом: лише GNSS / EKF Source Set 1, без перемикання EKF.'
}
Write-Host '[VINS-POSE-GRAPH] Контролер завантажує підписану місію безпосередньо в ArduPilot і двічі її перевіряє.'
Write-Host '[VINS-POSE-GRAPH] Mission Planner використовується лише як спостерігач.'
if ($profileConfig.execution.bootstrap_only -eq $true) {
    Write-Host '[VINS-POSE-GRAPH] Режим: лише qualification bootstrap із посадкою без переходу в AUTO.'
} else {
    Write-Host "[VINS-SQUARE-2K] Маршрут: квадрат $($profileConfig.route.side_m) м, $($profileConfig.route.loops) круги по $($profileConfig.route.nominal_loop_distance_m) м; потрібно reference distance >= $($profileConfig.route.required_reference_distance_m) м."
}
$bootstrapTrajectory = [string]$profileConfig.bootstrap.bootstrap_trajectory
if ($bootstrapTrajectory -eq 'vertical') {
    Write-Host '[VINS-POSE-GRAPH] Bootstrap VINS: вертикально 10 -> 20 -> 10 м.'
} elseif ($bootstrapTrajectory -eq 'lissajous_3d') {
    Write-Host '[VINS-POSE-GRAPH] Bootstrap VINS: контрольований 3D Lissajous, два yaw sweep, 15 с quality hold і 20 м scale-control.'
} elseif ($bootstrapTrajectory -eq 'preset_admission') {
    Write-Host "[VINS-POSE-GRAPH] Ініціалізація VINS: штатний pre-arm initializer активує перевірений пресет $($profileConfig.bootstrap.expected_initialization_preset_source_run_id), як у серії 8/8 PASS; після ARM контролер VINS не перезапускає."
} else {
    Write-Host "[VINS-POSE-GRAPH] Bootstrap VINS: 10 -> 20 -> 10 м на діагональних ділянках $($profileConfig.bootstrap.bootstrap_path_angle_deg)°."
}
if ($NavigationMode -eq 'gps_denied') {
    Write-Host '[VINS-POSE-GRAPH] Після initialization gate VINS ExternalNav стає єдиним джерелом XY/velocity/yaw для FCU Source Set 2.'
} else {
    Write-Host "[VINS-POSE-GRAPH] Після обов’язкового initialization gate VINS використовується лише для вимірювання."
}
Write-Host '[VINS-POSE-GRAPH] Architecture contract checks навмисно не входять до цього тесту.'
if ($Rosbag) {
    Write-Host '[VINS-POSE-GRAPH] Rosbag: прямо дозволено користувачем для цього запуску.'
} else {
    Write-Host '[VINS-POSE-GRAPH] Rosbag: вимкнено за замовчуванням.'
}
if ($PrintOnly) { Write-Host '[VINS-SQUARE-2K] Профіль і backend contract перевірено; політ не запущено.'; exit 0 }
if ($Backend -eq 'real_vehicle') {
    throw 'Контракти real_vehicle готові, але ARM реального дрона в першій SIM-кампанії заборонено. Потрібен окремий затверджений польотний Issue та майданчик.'
}

if ($bootstrapTrajectory -eq 'preset_admission') {
    $env:VINS_NEO_OVERLAY_SETUP = '.runtime/vins-neo-dev-overlay/install'
    Write-Host '[VINS-POSE-GRAPH] Обрано готовий контрольований VINS-NEO overlay із підтримкою initialization preset; перекомпіляція не виконується.'
}

$selectedDistro = if ($RuntimeVerified) {
    if (-not $Distro) { throw 'RuntimeVerified потребує явно переданий Distro.' }
    Write-Host "[VINS-POSE-GRAPH] Suite використовує вже перевірений WSL runtime: $Distro"
    $Distro
} else {
    Resolve-VerifiedQualificationDistro
}
$args = @('run', '-RouteQualification', '-RouteQualificationProfile', $relativeProfile, '-Distro', $selectedDistro)
if ($useHeadless) { $args += '-Headless' }
if ($Rosbag) {
    $args += '-Rosbag'
}
$latestState = Join-Path $repoRoot '.runtime\state\latest_run'
$previous = if (Test-Path $latestState) { (Get-Content -Raw $latestState).Trim() } else { $null }
$launcherRoot = Join-Path $PSScriptRoot 'logs\_launcher'
New-Item -ItemType Directory -Force -Path $launcherRoot | Out-Null
$launcher = $null
$savedErrorActionPreference = $ErrorActionPreference
$exitCode = 1
for ($attempt = 1; $attempt -le 2; $attempt++) {
    $launcher = Join-Path $launcherRoot ('{0}_{1}_attempt-{2}.log' -f (Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'), $PID, $attempt)
    try {
        # WSL readiness messages are intentionally written to stderr.
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot 'dev.ps1') @args 2>&1 |
            Tee-Object -FilePath $launcher
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($exitCode -eq 0) { break }
    $transcript = Get-Content -Raw -LiteralPath $launcher
    $attemptRunId = if (Test-Path $latestState) { (Get-Content -Raw $latestState).Trim() } else { $null }
    $runEvidence = ''
    if ($attemptRunId) {
        $attemptEvidence = Get-LatestEvidenceDirectory
        $evidenceCandidates = @(
            (Join-Path $repoRoot ".runtime\runs\$attemptRunId\stack.log"),
            $(if ($attemptEvidence) { Join-Path $attemptEvidence 'raw\scenario-events.jsonl' })
        )
        foreach ($candidate in $evidenceCandidates) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $runEvidence += "`n" + (Get-Content -Raw -LiteralPath $candidate)
            }
        }
    }
    $preArmStartupFailure = Test-PreArmStartupFailure `
        -ExitCode $exitCode `
        -Transcript $transcript `
        -RunEvidence $runEvidence
    if (-not $preArmStartupFailure -or $attempt -ge 2) { break }
    Write-Warning '[VINS-POSE-GRAPH] Доведену startup failure зафіксовано до ARM; виконується один чистий повтор.'
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot 'dev.ps1') stop -Distro $selectedDistro 2>&1 | Out-Host
    $ErrorActionPreference = $savedErrorActionPreference
    Start-Sleep -Seconds 3
}
$runId = if (Test-Path $latestState) { (Get-Content -Raw $latestState).Trim() } else { $null }
if ($runId -and $runId -ne $previous) {
    $evidence = Get-LatestEvidenceDirectory
    if (-not $evidence) { throw "Canonical evidence directory не знайдено для run $runId." }
    $pdf = Join-Path $evidence ('report\' + [string]$profileConfig.report.pdf_filename)
    Write-Host "[VINS-POSE-GRAPH] Evidence: $evidence"
    Write-Host "[VINS-POSE-GRAPH] Журнал launcher: $launcher"
    if ((Test-Path -LiteralPath $pdf) -and -not $NoOpenReport -and $visualMode -eq 'visual' -and $profileConfig.report.open_pdf_after_test) { Start-Process $pdf }
}
exit $exitCode

Set-Location "d:\HueTT\prepare for Phd\door to door2\multi_level_phuc"
$ErrorActionPreference = 'Stop'

function Get-LastMetric([string]$text, [string]$label) {
    $pattern = "(?im)^" + [regex]::Escape($label) + ":\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
    $matches = [regex]::Matches($text, $pattern)
    if ($matches.Count -gt 0) { return [double]$matches[$matches.Count - 1].Groups[1].Value }
    return [double]::NaN
}

function Get-StdDev([double[]]$vals) {
    if ($vals.Count -le 1) { return 0.0 }
    $mean = ($vals | Measure-Object -Average).Average
    $sumSq = 0.0
    foreach ($v in $vals) { $sumSq += ($v - $mean) * ($v - $mean) }
    return [math]::Sqrt($sumSq / ($vals.Count - 1))
}

$instances = Get-ChildItem -Path "instances" -Filter "50.10.*.txt" | Sort-Object Name
$variants = @(
    @{ Name = 'multilevel_time'; Exe = '.\\results\\bench\\multilevel_time.exe'; Type='multilevel' },
    @{ Name = 'multilevel_orient'; Exe = '.\\results\\bench\\multilevel_orient.exe'; Type='multilevel' },
    @{ Name = 'pure_tabu'; Exe = '.\\results\\bench\\tabu.exe'; Type='tabu' }
)

$runsPerInstance = 3
$rows = New-Object System.Collections.Generic.List[object]

foreach ($v in $variants) {
    foreach ($inst in $instances) {
        for ($run = 1; $run -le $runsPerInstance; $run++) {
            if ($v.Type -eq 'multilevel') {
                $args = @($inst.FullName, '4', '50', '20')
            } else {
                $args = @($inst.FullName, '50', '160')
            }

            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $output = & $v.Exe @args 2>&1 | Out-String
            $sw.Stop()

            $rows.Add([pscustomobject]@{
                variant = $v.Name
                instance = $inst.Name
                run = $run
                runtime_sec = [math]::Round($sw.Elapsed.TotalSeconds, 4)
                makespan = Get-LastMetric $output 'Makespan'
                drone_violation = Get-LastMetric $output 'Drone violation'
                waiting_violation = Get-LastMetric $output 'Waiting violation'
                fitness = Get-LastMetric $output 'Fitness'
            }) | Out-Null
        }
    }
}

$rawPath = "results/bench/benchmark_50_10_cfg_50x20_vs_50x160_raw.csv"
$rows | Export-Csv -Path $rawPath -NoTypeInformation

$summary = New-Object System.Collections.Generic.List[object]
$groups = $rows | Group-Object variant, instance
foreach ($g in $groups) {
    $valsTime = @($g.Group | ForEach-Object { [double]$_.runtime_sec })
    $valsFit = @($g.Group | ForEach-Object { [double]$_.fitness })
    $valsMk = @($g.Group | ForEach-Object { [double]$_.makespan })
    $valsDr = @($g.Group | ForEach-Object { [double]$_.drone_violation })
    $valsWt = @($g.Group | ForEach-Object { [double]$_.waiting_violation })

    $parts = $g.Name -split ',\s*'
    $summary.Add([pscustomobject]@{
        variant = $parts[0]
        instance = $parts[1]
        runs = $g.Count
        runtime_mean = [math]::Round((($valsTime | Measure-Object -Average).Average), 4)
        runtime_std = [math]::Round((Get-StdDev $valsTime), 4)
        fitness_mean = [math]::Round((($valsFit | Measure-Object -Average).Average), 6)
        fitness_best = [math]::Round((($valsFit | Measure-Object -Minimum).Minimum), 6)
        makespan_mean = [math]::Round((($valsMk | Measure-Object -Average).Average), 6)
        drone_violation_mean = [math]::Round((($valsDr | Measure-Object -Average).Average), 6)
        waiting_violation_mean = [math]::Round((($valsWt | Measure-Object -Average).Average), 6)
    }) | Out-Null
}

$summaryPath = "results/bench/benchmark_50_10_cfg_50x20_vs_50x160_summary.csv"
$summary | Sort-Object variant, instance | Export-Csv -Path $summaryPath -NoTypeInformation

$overallPath = "results/bench/benchmark_50_10_cfg_50x20_vs_50x160_overall.csv"
$overall = New-Object System.Collections.Generic.List[object]
foreach ($g in ($summary | Group-Object variant)) {
    $overall.Add([pscustomobject]@{
        variant = $g.Name
        runtime_mean_over_instances = [math]::Round((($g.Group.runtime_mean | ForEach-Object {[double]$_} | Measure-Object -Average).Average), 4)
        fitness_mean_over_instances = [math]::Round((($g.Group.fitness_mean | ForEach-Object {[double]$_} | Measure-Object -Average).Average), 6)
        fitness_best_over_instances = [math]::Round((($g.Group.fitness_best | ForEach-Object {[double]$_} | Measure-Object -Average).Average), 6)
    }) | Out-Null
}
$overall | Sort-Object variant | Export-Csv -Path $overallPath -NoTypeInformation

Write-Output "SUMMARY=$summaryPath"
Write-Output "OVERALL=$overallPath"

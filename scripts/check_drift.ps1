# Senior IT: Check for env drift
$Reqs = Get-Content -Path "requirements.txt"
$Installed = pip freeze

foreach ($Line in $Reqs) {
    if ($Line -match "==") {
        $Pkg = $Line.Split("==")[0]
        if ($Installed -notmatch "$Pkg==") {
            Write-Host "DRIFT DETECTED: $Pkg missing or version mismatch!" -ForegroundColor Red
        }
    }
}
Write-Host "Drift check complete."

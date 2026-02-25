param(
  [ValidateSet("patch","minor","major")]
  [string]$Bump = "patch"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$versionFile = Join-Path $root "VERSION"
$changelogFile = Join-Path $root "CHANGELOG.md"
$releaseNotesFile = Join-Path $root "RELEASE_NOTES.md"

if (-not (Test-Path $versionFile)) {
  "0.1.0" | Out-File -FilePath $versionFile -Encoding utf8
}

$current = (Get-Content $versionFile -Raw).Trim()
$parts = $current.Split(".")
if ($parts.Count -ne 3) {
  throw "VERSION must be semver format X.Y.Z"
}

$major = [int]$parts[0]
$minor = [int]$parts[1]
$patch = [int]$parts[2]

switch ($Bump) {
  "major" { $major += 1; $minor = 0; $patch = 0 }
  "minor" { $minor += 1; $patch = 0 }
  "patch" { $patch += 1 }
}

$next = "$major.$minor.$patch"
$date = Get-Date -Format "yyyy-MM-dd"

$log = git log --pretty=format:"- %s (%h)" -n 50
if (-not $log) {
  $log = "- maintenance"
}

$releaseNotes = @"
# Release $next

Date: $date

## Changes
$log
"@
$releaseNotes | Out-File -FilePath $releaseNotesFile -Encoding utf8

$changelogEntry = @"
## $next - $date
$log

"@

if (Test-Path $changelogFile) {
  $existing = Get-Content $changelogFile -Raw
  $header = "# Changelog`r`n`r`n"
  if ($existing.StartsWith($header)) {
    $tail = $existing.Substring($header.Length)
    ($header + $changelogEntry + $tail) | Out-File -FilePath $changelogFile -Encoding utf8
  } else {
    ("# Changelog`r`n`r`n" + $changelogEntry + $existing) | Out-File -FilePath $changelogFile -Encoding utf8
  }
} else {
  ("# Changelog`r`n`r`n" + $changelogEntry) | Out-File -FilePath $changelogFile -Encoding utf8
}

$next | Out-File -FilePath $versionFile -Encoding utf8
Write-Host "Bumped version: $current -> $next"
Write-Host "Updated: VERSION, CHANGELOG.md, RELEASE_NOTES.md"

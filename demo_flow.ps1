param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$Tenant = "",
  [ValidateRange(0, 365)][int]$DayOffset = 2,
  [ValidateRange(1, 365)][int]$ReservationDayOffset = 3,
  [string]$EmployeeName = "Magda",
  [string]$ServiceName = "Strzyzenie",
  [string]$ReservationServiceName = "Koloryzacja",
  [string]$ActorEmail = "owner@salon.pl",
  [string]$AdminApiKey = $env:ADMIN_API_KEY,
  [ValidateRange(5, 480)][int]$VisitDurationMin = 60,
  [ValidateRange(5, 60)][int]$SlotStepMin = 15,
  [ValidateRange(1, 20)][int]$SlotsLimit = 5,
  [string]$ReportFile = "",
  [switch]$NoStartApi,
  [switch]$KeepApiRunning
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$baseUri = $null
try {
  $baseUri = [Uri]$BaseUrl
} catch {
  throw "Invalid BaseUrl: $BaseUrl"
}

if ($baseUri.Scheme -notin @("http", "https")) {
  throw "BaseUrl must use http/https: $BaseUrl"
}

if ($baseUri.Scheme -eq "https" -and -not $NoStartApi) {
  throw "For https use -NoStartApi and run API separately with TLS termination."
}

$baseUrlNormalized = $BaseUrl.TrimEnd("/")
$apiPort = if ($baseUri.IsDefaultPort) { if ($baseUri.Scheme -eq "https") { 443 } else { 80 } } else { $baseUri.Port }
$isLocalBase = $baseUri.Host -in @("127.0.0.1", "localhost", "0.0.0.0")

if ([string]::IsNullOrWhiteSpace($Tenant)) {
  $Tenant = "demo-flow-" + (Get-Date).ToString("yyyyMMddHHmmss")
}

$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
if (-not $ReportFile) {
  $ReportFile = Join-Path $logsDir "demo_flow_last.json"
}

$report = [ordered]@{
  started_at = (Get-Date).ToString("o")
  status = "running"
  base_url = $baseUrlNormalized
  tenant = $Tenant
  day_offset = $DayOffset
  reservation_day_offset = $ReservationDayOffset
  employee_name = $EmployeeName
  service_name = $ServiceName
  reservation_service_name = $ReservationServiceName
  visit_duration_min = $VisitDurationMin
  slot_step_min = $SlotStepMin
  slots_limit = $SlotsLimit
  admin_api_key_used = -not [string]::IsNullOrWhiteSpace($AdminApiKey)
  api_started_here = $false
  api_reused = $false
}

$apiProcess = $null
$startedApiHere = $false
$currentStep = "preflight"

function Get-ErrorBody($err) {
  try {
    $response = $err.Exception.Response
    if ($null -eq $response) { return $null }
    $stream = $response.GetResponseStream()
    if ($null -eq $stream) { return $null }
    $reader = New-Object System.IO.StreamReader($stream)
    $body = $reader.ReadToEnd()
    $reader.Dispose()
    return $body
  } catch {
    return $null
  }
}

function Invoke-JsonApi {
  param(
    [string]$Method,
    [string]$Uri,
    [hashtable]$Headers = $null,
    $BodyObject = $null
  )

  $args = @{
    Method = $Method
    Uri = $Uri
    TimeoutSec = 10
  }
  if ($Headers) { $args.Headers = $Headers }
  if ($null -ne $BodyObject) {
    $args.ContentType = "application/json"
    $args.Body = ($BodyObject | ConvertTo-Json -Depth 8)
  }

  try {
    return Invoke-RestMethod @args
  } catch {
    $body = Get-ErrorBody $_
    if ($body) {
      throw "HTTP $Method $Uri failed: $body"
    }
    throw "HTTP $Method $Uri failed: $($_.Exception.Message)"
  }
}

function Wait-Endpoint([string]$url, [int]$retries = 40) {
  for ($i = 0; $i -lt $retries; $i++) {
    try {
      $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
      if ($r.StatusCode -eq 200) { return }
    } catch {}
    Start-Sleep -Milliseconds 500
  }
  throw "Endpoint not ready: $url"
}

function Test-Endpoint([string]$url) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

try {
  $currentStep = "api_bootstrap"
  if (-not $NoStartApi) {
    if (Test-Endpoint "$baseUrlNormalized/ping") {
      $report.api_reused = $true
    } else {
      if (-not $isLocalBase) {
        throw "BaseUrl host '$($baseUri.Host)' is not local. Use -NoStartApi for remote API."
      }
      $python = Join-Path $root ".venv\Scripts\python.exe"
      if (-not (Test-Path $python)) { throw "Missing $python" }

      $bindHost = if ($baseUri.Host -eq "localhost") { "127.0.0.1" } else { $baseUri.Host }
      $stdoutLog = Join-Path $logsDir "demo_flow_uvicorn.log"
      $stderrLog = Join-Path $logsDir "demo_flow_uvicorn.err.log"
      $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $bindHost, "--port", "$apiPort") `
        -PassThru `
        -WorkingDirectory $root `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
      $startedApiHere = $true
      $report.api_started_here = $true
      $report.api_pid = $apiProcess.Id
    }
  }

  Wait-Endpoint "$baseUrlNormalized/ping"
  Write-Host "[1/10] API ready"

  $h = @{ "X-Tenant-Slug" = $Tenant }
  $ha = @{ "X-Tenant-Slug" = $Tenant; "X-Actor-Email" = $ActorEmail }
  $hOps = @{ "X-Tenant-Slug" = $Tenant }
  if (-not [string]::IsNullOrWhiteSpace($AdminApiKey)) {
    $hOps["X-Admin-Api-Key"] = $AdminApiKey
  }
  $day = (Get-Date).AddDays($DayOffset).ToString("yyyy-MM-dd")
  $reservationDay = (Get-Date).AddDays($ReservationDayOffset).ToString("yyyy-MM-dd")
  $reservationDt = (Get-Date).ToUniversalTime().Date.AddDays($ReservationDayOffset).AddHours(14).ToString("yyyy-MM-ddTHH:mm:ssZ")

  $currentStep = "availability"
  Write-Host "[2/10] Availability + block"
  $availability = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/availability/day" -Headers $h -BodyObject @{
      employee_name = $EmployeeName
      day = $day
      is_day_off = $false
      start_hour = 8
      end_hour = 18
      note = "demo-flow"
    }
  $block = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/availability/blocks" -Headers $h -BodyObject @{
      employee_name = $EmployeeName
      start_dt = "$day`T12:00:00"
      end_dt = "$day`T13:00:00"
      reason = "lunch"
    }

  $currentStep = "buffers_slots"
  Write-Host "[3/10] Buffers + slot recommendations"
  $encodedService = [uri]::EscapeDataString($ServiceName)
  $encodedEmployee = [uri]::EscapeDataString($EmployeeName)
  Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/buffers/service/$encodedService" -Headers $h -BodyObject @{
      before_min = 10
      after_min = 15
    } | Out-Null
  Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/buffers/employee/$encodedEmployee" -Headers $h -BodyObject @{
      before_min = 5
      after_min = 5
    } | Out-Null
  $slots = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/slots/recommendations?day=$day&employee_name=$encodedEmployee&service_name=$encodedService&duration_min=$VisitDurationMin&step_min=$SlotStepMin&limit=$SlotsLimit" -Headers $h
  if (-not $slots -or $slots.Count -lt 1) {
    throw "No slot recommendations returned"
  }

  $currentStep = "visit_status"
  Write-Host "[4/10] Visit + status flow"
  $visit = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/visits" -Headers $h -BodyObject @{
      dt = $slots[0].start_dt
      client_name = "Jan DemoFlow"
      client_phone = "+48100100100"
      employee_name = $EmployeeName
      service_name = $ServiceName
      price = 210
      duration_min = $VisitDurationMin
    }
  Invoke-JsonApi -Method "Patch" -Uri "$baseUrlNormalized/api/visits/$($visit.id)/status" -Headers $ha -BodyObject @{
      status = "confirmed"
      note = "demo confirm"
    } | Out-Null
  $visitAfter = Invoke-JsonApi -Method "Patch" -Uri "$baseUrlNormalized/api/visits/$($visit.id)/status" -Headers $ha -BodyObject @{
      status = "arrived"
      note = "demo arrive"
    }
  $visitHistory = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/visits/$($visit.id)/history" -Headers $h

  $currentStep = "crm"
  Write-Host "[5/10] CRM search/detail/note"
  $search = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/clients/search?q=Jan&limit=5" -Headers $h
  if (-not $search -or $search.Count -lt 1) {
    throw "Client search returned empty list"
  }
  $clientId = [int]$search[0].id
  $clientDetail = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/clients/$clientId" -Headers $h
  $note = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/clients/$clientId/notes" -Headers $ha -BodyObject @{
      note = "Klient potwierdzil termin"
    }

  $currentStep = "reservation_create_assistant"
  Write-Host "[6/10] Reservation create + assistant"
  $reservation = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/public/$Tenant/reservations" -BodyObject @{
      requested_dt = $reservationDt
      client_name = "Ola DemoFlow"
      service_name = $ReservationServiceName
      phone = "+48200200200"
      note = "demo reservation"
    }
  $assistantBefore = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/reservations/assistant?limit=5" -Headers $h

  $currentStep = "reservation_status_convert"
  Write-Host "[7/10] Reservation status + convert"
  $reservationAfterStatus = Invoke-JsonApi -Method "Patch" -Uri "$baseUrlNormalized/api/reservations/$($reservation.id)/status" -Headers $ha -BodyObject @{
      status = "contacted"
    }
  $convertedVisit = Invoke-JsonApi -Method "Post" -Uri "$baseUrlNormalized/api/reservations/$($reservation.id)/convert" -Headers $ha -BodyObject @{
      employee_name = $EmployeeName
      price = 260
    }
  $reservationHistory = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/reservations/$($reservation.id)/history" -Headers $h

  $currentStep = "pulse_assistant"
  Write-Host "[8/10] Pulse + assistant after"
  $pulse = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/pulse/day?day=$day" -Headers $h
  $assistantAfter = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/reservations/assistant?limit=5" -Headers $h
  $integrity = Invoke-JsonApi -Method "Get" -Uri "$baseUrlNormalized/api/integrity/conversions?limit=20" -Headers $hOps

  $currentStep = "report_build"
  Write-Host "[9/10] Build summary"
  $report.status = "ok"
  $report.finished_at = (Get-Date).ToString("o")
  $report.day = $day
  $report.reservation_day = $reservationDay
  $report.availability_day_set = $availability.day
  $report.block_id = $block.id
  $report.slots_count = $slots.Count
  $report.first_slot_start = $slots[0].start_dt
  $report.visit_id = $visit.id
  $report.visit_status_after = $visitAfter.status
  $report.visit_history_count = $visitHistory.Count
  $report.client_id = $clientId
  $report.client_visits_count = $clientDetail.visits_count
  $report.note_id = $note.id
  $report.reservation_id = $reservation.id
  $report.reservation_status_after = $reservationAfterStatus.status
  $report.reservation_history_count = $reservationHistory.Count
  $report.converted_visit_id = $convertedVisit.id
  $report.converted_source_reservation_id = $convertedVisit.source_reservation_id
  $report.assistant_before_count = $assistantBefore.Count
  $report.assistant_after_count = $assistantAfter.Count
  $report.pulse_visits_count = $pulse.visits_count
  $report.pulse_conversion_rate = $pulse.conversion_rate
  $report.integrity_ok = $integrity.ok
  $report.integrity_issues_count = $integrity.issues_count
  $report.success_criteria = [ordered]@{
    slots_count_min_1 = ($slots.Count -ge 1)
    visit_status_arrived = ($visitAfter.status -eq "arrived")
    reservation_status_contacted = ($reservationAfterStatus.status -eq "contacted")
    converted_visit_exists = ($convertedVisit.id -gt 0)
    converted_source_matches_reservation = ($convertedVisit.source_reservation_id -eq $reservation.id)
    integrity_report_ok = [bool]$integrity.ok
  }
}
catch {
  $report.status = "failed"
  $report.finished_at = (Get-Date).ToString("o")
  $report.failed_step = $currentStep
  $report.error = $_.Exception.Message
  throw
}
finally {
  $report | ConvertTo-Json -Depth 8 | Set-Content $ReportFile
  Write-Host "[10/10] Report: $ReportFile"
  if ($report.status -eq "ok") {
    Write-Host "Demo flow OK"
    Write-Host ("- tenant: " + $report.tenant)
    Write-Host ("- day: " + $report.day)
    Write-Host ("- visit_id: " + $report.visit_id + " (" + $report.visit_status_after + ")")
    Write-Host ("- reservation_id: " + $report.reservation_id + " -> visit_id: " + $report.converted_visit_id)
    Write-Host ("- pulse visits: " + $report.pulse_visits_count + ", conversion_rate: " + $report.pulse_conversion_rate)
    Write-Host ("- integrity ok: " + $report.integrity_ok + ", issues: " + $report.integrity_issues_count)
  }
  if ($startedApiHere -and -not $KeepApiRunning -and $apiProcess -and -not $apiProcess.HasExited) {
    Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
  }
}

# Richtet die stündliche Windows-Aufgabe "Superkugel Hörbuch-Eingang" ein (nur für den aktuellen Benutzer,
# keine Administratorrechte, läuft ohne Fenster). Erneuter Aufruf ersetzt die Aufgabe.
# Aufruf:  powershell -ExecutionPolicy Bypass -File scripts\install_inbox_task.ps1 [-Inbox <Ordner>]
param(
    [string]$Inbox = (Join-Path (Split-Path $PSScriptRoot -Parent) "superkugel-eingang"),
    [string]$AwsProfile = "superkugel-importer"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Python-Umgebung fehlt: $pythonw" }
New-Item -ItemType Directory -Force $Inbox | Out-Null

$action = New-ScheduledTaskAction -Execute $pythonw -WorkingDirectory $root `
    -Argument "`"$root\scripts\superkugel_admin.py`" --profile $AwsProfile inbox `"$Inbox`""
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Superkugel Hoerbuch-Eingang" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Importiert neue Hörbücher aus $Inbox in die Superkugel-Bibliothek (Protokoll: sync-log.jsonl, Fehler: sync-fehler.log)." `
    -Force | Out-Null
Write-Host "Aufgabe eingerichtet: stündlich, erster Lauf in ca. 5 Minuten. Eingang: $Inbox"

# Legt für den IAM-Benutzer "superkugel-importer" einen Zugriffsschlüssel an und speichert ihn
# im lokalen AWS-Profil "superkugel-importer". Der geheime Schlüssel wird nie angezeigt.
# Voraussetzung: Stack ist mit dem ImporterUser bereitgestellt; Profil "superkugel-admin" funktioniert.
# Aufruf:  powershell -ExecutionPolicy Bypass -File scripts\setup_importer_profile.ps1
$ErrorActionPreference = "Stop"
$existing = aws iam list-access-keys --user-name superkugel-importer --profile superkugel-admin --query "length(AccessKeyMetadata)" --output text
if ([int]$existing -ge 1) {
    Write-Host "superkugel-importer hat bereits einen Zugriffsschlüssel. Abbruch (alten Schlüssel zuerst in der Konsole löschen)."
    exit 1
}
$k = aws iam create-access-key --user-name superkugel-importer --profile superkugel-admin --output json | ConvertFrom-Json
aws configure set aws_access_key_id $k.AccessKey.AccessKeyId --profile superkugel-importer
aws configure set aws_secret_access_key $k.AccessKey.SecretAccessKey --profile superkugel-importer
aws configure set region eu-north-1 --profile superkugel-importer
Remove-Variable k
# Neue IAM-Schlüssel gelten erst nach einigen Sekunden
$ErrorActionPreference = "Continue"
for ($i = 0; $i -lt 12; $i++) {
    $arn = aws sts get-caller-identity --profile superkugel-importer --query Arn --output text 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "Profil eingerichtet als: $arn"; exit 0 }
    Start-Sleep -Seconds 5
}
Write-Host "Schlüssel angelegt, aber noch nicht gültig – in einer Minute erneut prüfen: aws sts get-caller-identity --profile superkugel-importer"

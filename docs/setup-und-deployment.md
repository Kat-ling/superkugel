# Einrichtung und Bereitstellung (nur für den Administrator)

Dauer beim ersten Mal: ca. 2–3 Stunden. Alles, was eine Zustimmung, ein Passwort oder eine
Zahlung braucht, ist mit ✋ markiert – das kann nur ein Mensch erledigen.

## 0. Werkzeuge auf dem Admin-PC

```bash
winget install Amazon.AWSCLI
```
```bash
winget install Amazon.SAM-CLI
```
```bash
npm install -g ask-cli
```
Python 3.12+ ist vorhanden. Im Projektordner:
```bash
python -m venv .venv
```
```bash
.venv/Scripts/pip install -r requirements-dev.txt
```

## 1. Amazon-Konto: alles über **dein** Konto ✋

Ein Skill im Entwicklungsmodus läuft auf allen Echo-Geräten, die auf **dasselbe Amazon-Konto** wie
der Developer-Account registriert sind. Betatests laufen nach 90 Tagen ab, das ist also nicht geeignet.
Da deine Schwiegermutter kein Amazon-Konto hat und keines braucht, ist die einfachste und
wartungsärmste Lösung: **Developer-Account und Echo Dot laufen beide auf deinem Amazon-Konto.**
Sie muss sich nirgends anmelden, und du verwaltest alles aus der Ferne in deiner Alexa-App.

| Variante | Bewertung |
|---|---|
| **Dein Konto für Developer + Echo** | ✅ empfohlen: kein neues Konto, kein Ablaufdatum, Fernwartung über deine App |
| Neues Konto für sie anlegen | ❌ zusätzliches Konto mit Passwort und 2FA, das du ohnehin verwalten müsstest, kein Vorteil |
| Betatest-Einladung | ❌ endet nach 90 Tagen |
| Amazon Household | ❌ nicht nötig, macht Entwicklungs-Skills nicht zusätzlich verfügbar |

### Schritte

1. ✋ Auf https://developer.amazon.com mit **deinem** Amazon-Login (amazon.de) anmelden und das
   kostenlose Entwicklerprofil anlegen (Name, Land, Entwicklungsbedingungen akzeptieren).
   2-Faktor-Anmeldung für dein Amazon-Konto aktivieren, falls noch nicht geschehen.
2. ✋ **Echo Dot auf dein Konto registrieren** (einmal vor Ort bei ihr):
   - Ist der Echo noch auf ein anderes Konto registriert, zuerst dort abmelden oder ihn zurücksetzen
     (Aktionstaste ca. 25 Sekunden gedrückt halten, bis der Ring orange leuchtet).
   - Deine Alexa-App → Geräte → **+** → Gerät hinzufügen → Amazon Echo → mit **ihrem WLAN** verbinden.
3. In deiner Alexa-App unter Geräte → ihr Echo die **Geräteeinstellungen** setzen:
   - Name, z. B. „Echo Mama“ (damit du ihn von deinen eigenen Geräten unterscheidest)
   - **Gerätestandort** = ihre Adresse (sonst bekommt sie Wetter und Uhrzeit für deinen Wohnort)
   - Zeitzone *Europa/Wien*, Sprache *Deutsch*, Maßeinheiten *metrisch*
4. ✋ **Schutzeinstellungen – wichtig, weil dein Konto und dein Zahlungsmittel dahinterstehen:**
   - *Einstellungen → Kontoeinstellungen → Einkaufen per Sprache*: **aus** (oder mindestens einen Sprachcode setzen).
   - *Einstellungen → Benachrichtigungen → Amazon Shopping*: aus, sonst kündigt ihr Echo **deine** Pakete an.
   - *Kommunikation*: Drop In für ihr Gerät aus, außer ihr vereinbart es ausdrücklich. Anrufe über Alexa sind optional.
   - *Listen, Kalender, Erinnerungen* gelten für das ganze Konto: Was sie auf „die Einkaufsliste“ setzt,
     landet auf deiner Liste, und verknüpfte Kalender kann sie abfragen. Am besten keinen privaten
     Kalender verknüpfen, oder das bewusst so lassen.
   - *Alexa-Datenschutz → Aufnahmen verwalten*: automatisches Löschen der Sprachaufnahmen aktivieren
     (z. B. nach 3 Monaten oder gar nicht speichern).
5. ✋ **Mit deiner Schwiegermutter besprechen** und ihr Einverständnis einholen: Ihre Sprachaufnahmen
   liegen in deinem Amazon-Konto, und Gesprächsinhalte gehen an OpenAI.

**Mehrere Echos in deinem Konto:** Auch deine eigenen Echo-Geräte können „Superkugel“ nutzen. Damit
nichts vermischt wird, speichert der Skill Hörbuch-Lesezeichen und Gesprächsverlauf **pro Gerät**
(pseudonymisiert aus Konto- und Geräte-ID). Die Bibliothek ist für alle Geräte dieselbe. Wird ihr
Echo einmal zurückgesetzt und neu registriert, bekommt er eine neue Geräte-ID: Die Hörbücher bleiben
erhalten, die Lesezeichen beginnen von vorne.

## 2. OpenAI ✋

1. ✋ Auf https://platform.openai.com ein **eigenes Projekt** „superkugel“ anlegen.
2. ✋ **Prepaid-Guthaben** (z. B. 5–10 $) aufladen und **Auto-Recharge ausschalten** → harte Obergrenze.
3. ✋ Projekt-Limits setzen (Usage → Limits), Modellzugriff auf `gpt-6-luna` beschränken.
4. ✋ Einen **Projekt-API-Schlüssel** erzeugen. Nicht in Dateien speichern, sondern direkt in Schritt 3.5 verwenden.
5. Datenschutz: Der Skill sendet `store: false`; Gesprächsinhalte werden nicht zum Training
   verwendet (API-Standard). Die Nutzerin darüber informieren ✋.

## 3. AWS ✋

1. ✋ AWS-Konto anlegen (Kreditkarte nötig; bei normaler Nutzung bleiben die Kosten im Cent-Bereich, siehe `kosten.md`).
2. ✋ Root-Konto mit MFA sichern.
3. CLI-Zugang für das **Projektkonto** einrichten. Bewährter Weg (so umgesetzt):
   - Im Projektkonto unter IAM einen Benutzer `superkugel-admin` mit Konsolenzugang, **MFA** und
     `AdministratorAccess` anlegen.
   - Für ihn einen Zugriffsschlüssel (Anwendungsfall CLI) erzeugen und lokal hinterlegen ✋ (nie in Dateien im Projekt):
     ```powershell
     aws configure --profile superkugel-admin
     ```
   - Prüfen: `aws sts get-caller-identity --profile superkugel-admin` muss das Projektkonto zeigen, nicht `root`.
   - Den Schlüssel deaktivieren, wenn gerade nicht deployt wird (IAM → Benutzer → Sicherheitsanmeldeinformationen).

   Alternativen: `aws login --profile superkugel-admin` (Konsolen-Anmeldung, ohne dauerhafte Schlüssel; schlug in
   dieser Organisation mit „400 Bad Request“ fehl) oder IAM Identity Center (`aws configure sso`) – nur sinnvoll,
   wenn dort **Multi-Account-Berechtigungen → Berechtigungssätze** verfügbar sind. Identity Center existiert nur in
   **einer** Region; das betrifft nur die Anmeldung, nicht die Skill-Ressourcen.
4. Region für **alle Skill-Ressourcen: eu-north-1 (Stockholm)**. Alexa unterstützt Lambda-Funktionen in
   allen Lambda-Regionen, darunter EU (Stockholm). Amazon empfiehlt für Europa zwar Irland (eu-west-1),
   der Unterschied liegt aber bei wenigen Hundertstelsekunden. Grund für Stockholm: Die Organisationsrichtlinie (SCP) des
   Superkugel-Kontos erlaubt nur diese Region (geprüft 25.10.2026: Lambda, DynamoDB, S3, SSM, SNS,
   CloudWatch, CloudFormation, KMS in eu-north-1 erlaubt; eu-west-1, eu-central-1, us-east-1 gesperrt).
   Konto: das **Projektkonto** (nicht das Management-Konto), Benutzer `superkugel-admin`.
5. ✋ Den OpenAI-Schlüssel als **SecureString** ablegen (die Eingabe erscheint nicht in Dateien):
   ```bash
   aws ssm put-parameter --profile superkugel-admin --region eu-north-1 --name /superkugel/openai-api-key --type SecureString --value "$(read -rsp 'OpenAI-Key: ' k; echo $k)"
   ```

## 4. Skill anlegen (Alexa Developer Console)

1. https://developer.amazon.com/alexa/console/ask → **Create Skill**
   - Name „Superkugel“, Sprache **Deutsch (DE)**, Modell **Custom**, Hosting **Provision your own**.
   - Vorlage „Start from Scratch“.
2. **Skill-ID** kopieren (amzn1.ask.skill.…).
3. Build → Interfaces → **Audio Player** einschalten. Build → **Permissions** → **Reminders** einschalten (ab v1.2;
   entspricht `permissions` in `skill-package/skill.json`), danach in der Alexa-App die Berechtigung erteilen
   (`betrieb-und-wartung.md`, Abschnitt Version 1.2).
4. Build → JSON Editor → Inhalt von `skill-package/interactionModels/custom/de-DE.json` einfügen → **Save** → **Build Model**.
   Alternativ per CLI (nach `ask configure` ✋):
   ```bash
   ask smapi set-interaction-model --skill-id amzn1.ask.skill.XXXX --stage development --locale de-DE --interaction-model "file:skill-package/interactionModels/custom/de-DE.json"
   ```

## 5. Backend bereitstellen (AWS SAM)

```bash
cp infra/samconfig.toml.example infra/samconfig.toml
```
In `infra/samconfig.toml` Skill-ID und Alarm-E-Mail eintragen, dann:
```bash
sam build --template infra/template.yaml
```
```bash
sam deploy --config-file infra/samconfig.toml --profile superkugel-admin
```
(Falls `sam build` auf Windows wegen Paketen für arm64 meckert: `sam build --use-container`, benötigt Docker.)

Danach:
- ✋ Die Bestätigungsmail von AWS SNS öffnen und **Confirm subscription** klicken.
- ✋ Budget-Warnung anlegen (das Template kann das in Stockholm nicht), im **Management-Konto**
  (dort läuft die Sammelrechnung): Konsole → *Abrechnung und Kostenmanagement → Budgets → Budget erstellen* →
  Vorlage „Monatliches Kostenbudget“, 5 $, deine E-Mail. Optional unter *Filter* nur das Konto Superkugel wählen.
- Ausgabe `SkillFunctionArn` kopieren → Developer Console → Build → **Endpoint** → AWS Lambda ARN →
  Feld *Default* (und *Europe and India*) → **Save Endpoints**.
- `.env` aus `.env.example` anlegen, `AUDIO_BUCKET` und `ALERT_TOPIC_ARN` aus der Ausgabe eintragen.

## 6. Testen, bevor sie es benutzt

1. Developer Console → **Test** → „Development“ aktivieren. Tippen: `öffne superkugel`, dann `was ist ein apfelstrudel`.
   ⚠️ Das ist der Simulator – **kein** Gerätetest.
2. Ein freies Testhörbuch importieren (siehe `hoerbuecher-und-thalia.md`, z. B. LibriVox, gemeinfrei).
3. Hardware-Testplan in `tests/acceptance/ACCEPTANCE_TESTS.md` am Echo Dot abarbeiten.

## 7. Aktivierung auf ihrem Echo Dot

Da Developer-Account und Echo auf **deinem** Konto laufen, ist der Skill **automatisch** auf ihrem
Echo (und deinen eigenen) verfügbar, sobald „Development“ im Test-Tab aktiv ist. In deiner Alexa-App
unter Skills → Meine Skills → *Entwicklung* erscheint „Superkugel“ (dort ggf. aktivieren).

**Optionale Vereinfachung (deine Alexa-App):** Routine anlegen
- Auslöser *Wenn du sagst*: „Mein Krimi“ → Aktion *Benutzerdefiniert*: „sag Superkugel spiel mein Hörbuch weiter“
- Auslöser: „Ich möchte ratschen“ → Aktion *Skills* → Superkugel
- Bei *Von* bzw. *Gerät* jeweils **ihren Echo** auswählen, damit die Antwort dort kommt.

Danach reicht „Alexa, mein Krimi“. **[am Gerät prüfen – Verhalten der Aktion „Benutzerdefiniert“ ist nicht dokumentiert garantiert]**

## 8. Konfiguration ändern

Stimme/Stil/Anrede/Limits: Werte in `infra/samconfig.toml` (`parameter_overrides`) ändern und
erneut `sam deploy` ausführen. Mögliche Werte:

| Parameter | Werte | Standard |
|---|---|---|
| `SpeechStyle` | `kaernten`, `bayern`, `standard` | `kaernten` |
| `AlexaVoice` | `alexa`, `Vicki`, `Marlene`, `Hans` | `alexa` (eingesetzt: `Vicki`) |
| `SpeechRate` | `85%` … `105%` | `100%` |
| `AddressForm` | `du`, `sie` | `sie` (eingesetzt: `du`) |
| `UserName` | Vorname der Nutzerin | leer |
| `OpenAiModel` | jedes Responses-API-Modell | `gpt-6-luna` |
| `DailyCostLimitUsd` / `MonthlyCostLimitUsd` | Zahl | 0,5 / 8 |

Weitere Feineinstellungen (Timeouts, Verlaufslänge, Spul-Sekunden) sind Umgebungsvariablen in
`src/superkugel/config.py` und können in `template.yaml` ergänzt werden.

## Reproduzierbarkeit

- Abhängigkeiten exakt gepinnt (`src/requirements.txt`, `requirements-dev.txt`).
- Interaction Model wird aus dem Code erzeugt (`scripts/build_interaction_model.py`); CI prüft, dass es aktuell ist.
- Infrastruktur vollständig in `infra/template.yaml`; Tabelle und Bucket haben `DeletionPolicy: Retain`
  (versehentliches Löschen des Stacks löscht keine Hörbücher oder Fortschritte).

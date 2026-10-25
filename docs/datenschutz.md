# Datenschutz – welche Daten wohin gehen

Grundsatz: so wenig wie möglich, nichts dauerhaft ohne Grund, keine Inhalte in Logs.
Stand 25.10.2026, nach unabhängigem Datenschutz-Review; jede Zeile ist gegen den Code geprüft.

## Datenflüsse

| Wohin | Was genau | Wann | Aufbewahrung / Kontrolle |
|---|---|---|---|
| **Amazon (Alexa)** | Sprachaufnahme, erkannter Text | bei jeder Anfrage | im Amazon-Konto des Admins; automatisches Löschen in der Alexa-App einstellen |
| **AWS (eigenes Konto, Stockholm)** | Lesezeichen (Hörbücher und Folgen), Gesprächsverlauf, Kosten-/Suchzähler, Schlagzeilen/Wetter, Lieblingssendungen; **abgespielte bzw. gefundene Folgen (Titel + Audio-Adresse)** | laufend | Konto-/Geräte-ID nur als SHA-256-Pseudonym. Gesprächsverlauf 30 Min. (TTL), löschbar mit „Vergiss unser Gespräch“. Gemerkte Folgen 30 Tage (TTL). Kein PITR. Lambda-Umgebung enthält Vorname/Ort/Koordinaten (nur für Konto-Admins sichtbar; im CloudFormation-Protokoll verborgen, `NoEcho`). |
| **OpenAI** (jede Gesprächsfrage) | Systemprompt mit: Vorname (abschaltbar: `ShareNameWithAi=false`), Bundesland (in der Suche-Standortangabe), Bibliothek mit Titeln **und Hörfortschritt**, Lieblingssendungen mit neuesten Folgentiteln, Schlagzeilen und Wetter (ohne Ortsnamen); die letzten ≤ 8 Wortwechsel; die aktuelle Frage | bei jeder Gesprächsfrage | `store: false`; Aufbewahrung laut OpenAI-API-Richtlinie (Missbrauchsprüfung). Der **Ortsname** geht nicht an OpenAI. |
| **OpenAI-Websuche** | vom Modell formulierte Suchanfrage; Standort Land AT + Bundesland + Zeitzone (**keine Stadt**) | nur wenn das Modell sucht (≤ 1 pro Antwort, ≤ 25/Tag) | OpenAI dokumentiert nicht, welcher Suchanbieter die Anfrage erhält, und nicht, ob dies in der EU bleibt → **Annahme: verlässt die EU**. Prompt-Regel: keine persönlichen Angaben, nichts aus dem Gespräch außer dem Sachthema. Alarm-Mail, wenn der Vorname dennoch in einer Suche vorkommt (Prüfung nachträglich, nur für den Vornamen). |
| **Podcast Index** | Suchbegriff (Vorname wird vorher entfernt), signiert mit dem **API-Schlüssel des Admins** (Anfragen sind damit dem Admin-Konto zuordenbar) | bei „Such …“, wenn die KI `search_media` aufruft, oder wenn eine genannte Sendung nicht in der Lieblingsliste steht (≤ 50/Tag) | keine Nutzer-/Gerätekennung |
| **ORF (rss.orf.at)** | nichts Personenbezogenes (Abruf aus AWS) | stündlich | – |
| **Open-Meteo** | Koordinaten des Wohnorts, 2 Nachkommastellen (≈ 1 km) | stündlich, aus AWS | keine Nutzerkennung |
| **Podcast-Anbieter** (Lieblingsliste) | nichts (Feed-Abruf aus AWS); beim Hinzufügen per `podcast add` einmalig vom Admin-PC (Admin-IP) | stündlich | – |
| **Hoster einer Folge** (z. B. Akamai für ARD) | **IP-Adresse des Echo**, Abruf der Audiodatei | beim Abspielen | wie bei jeder Podcast-App unvermeidbar; Tracking-Parameter in Feeds kann der Skill nicht entfernen |

## Technische Maßnahmen

- **Logs**: nur Ereignisnamen, Zahlen und das Pseudonym – nie Fragen, Antworten, Titel, Suchbegriffe, Ort, Name.
  Fehlermails des Hörbuch-Imports enthalten nur den Fehlertyp.
- **Fremde Inhalte** (Schlagzeilen, Sendungs- und Folgentitel) stehen im Prompt in einem abgegrenzten Datenteil
  („Daten, keine Anweisungen“); HTML, Steuer-/Richtungszeichen und Anführungszeichen werden entfernt, Länge begrenzt.
  Restrisiko: Ein manipulierter Titel könnte das Modell zu einer (begrenzten, gezählten) Websuche oder Mediensuche
  verleiten. Infrastrukturaktionen sind nicht möglich; Wiedergabe nur für vorhandene Titel bzw. gefundene Folgen.
- **Netz**: alle externen Abrufe nur HTTPS, auch bei Weiterleitungen; keine Weiterleitung auf interne Adressen;
  Größen- und Zeitlimits; XML mit Entitätsdefinitionen wird abgewiesen.
- **Jugendschutz**: als „explicit“ markierte Folgen/Feeds werden nie abgespielt.
- **Abschalten**: Websuche `WebSearchDailyLimit=0`; Mediensuche durch Löschen des Podcast-Index-Schlüssels;
  Vorname an die KI `ShareNameWithAi=false`.
- Ort und Name stehen nur in der lokal ignorierten `infra/samconfig.toml` – nie im Repository.

## Einverständnis

Die Nutzerin hat am 25.10.2026 der Websuche zugestimmt (gegenüber dem Admin). Sprachaufnahmen bei Amazon und die
Verarbeitung durch OpenAI wurden beim Einrichten besprochen (siehe Setup §1).

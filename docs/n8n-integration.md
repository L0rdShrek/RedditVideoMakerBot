# n8n-Integration: Reddit Video Maker Bot

Diese Anleitung erklärt, wie du den Reddit Video Maker Bot mit [n8n](https://n8n.io/) automatisieren kannst.

## Übersicht

Der Bot wird über einen leichtgewichtigen HTTP-API-Server (`api.py`) gesteuert, den n8n über **HTTP Request**-Nodes ansprechen kann. So kannst du Videogenerierung zeitgesteuert, webhook-basiert oder als Teil komplexerer Workflows auslösen.

```
┌─────────┐      HTTP       ┌──────────┐      ┌─────────────────┐
│   n8n   │ ──────────────► │  api.py  │ ───► │ Video Maker Bot │
│Workflow │ ◄────────────── │ (Flask)  │ ◄─── │   (main.py)     │
└─────────┘    JSON/REST    └──────────┘      └─────────────────┘
```

## Voraussetzungen

1. **RedditVideoMakerBot** ist installiert und `config.toml` ist konfiguriert
2. **n8n** ist installiert ([Installationsanleitung](https://docs.n8n.io/hosting/installation/))
3. **Python 3.10+** mit allen Dependencies (`pip install -r requirements.txt`)
4. **FFmpeg** ist installiert

## Schnellstart

### 1. API-Server starten

```bash
cd RedditVideoMakerBot
python api.py --host 0.0.0.0 --port 5000
```

Der Server läuft nun auf `http://localhost:5000`.

### 2. n8n-Workflow importieren

1. Öffne die n8n-Oberfläche (standardmäßig `http://localhost:5678`)
2. Gehe zu **Workflows** → **Import from File**
3. Wähle die Datei `n8n/workflow_reddit_video_bot.json`
4. Passe die URLs an, falls der API-Server auf einem anderen Host/Port läuft
5. Aktiviere den Workflow

## API-Endpunkte

### Health Check
```
GET /api/health
```
Antwort:
```json
{"status": "ok", "version": "3.4.0"}
```

### Video generieren
```
POST /api/generate
Content-Type: application/json

{
    "post_id": "abc123",           // Optional: Bestimmter Reddit-Post
    "subreddit": "AskReddit",     // Optional: Subreddit überschreiben
    "config": {                    // Optional: Konfiguration überschreiben
        "settings": {
            "theme": "dark",
            "storymode": false
        }
    }
}
```
Antwort (HTTP 202):
```json
{"job_id": "550e8400-e29b-41d4-a716-446655440000", "status": "queued"}
```

### Job-Status abfragen
```
GET /api/jobs/{job_id}
```
Antwort:
```json
{
    "job_id": "550e8400-...",
    "status": "completed",
    "created_at": "2026-03-12T10:00:00+00:00",
    "completed_at": "2026-03-12T10:05:30+00:00",
    "result": {
        "reddit_id": "abc123",
        "thread_title": "What is your best life hack?",
        "number_of_comments": 8,
        "video_length_seconds": 120,
        "output_files": ["results/What is your best life hack?/final.mp4"]
    }
}
```

Mögliche Status-Werte: `queued`, `running`, `completed`, `failed`

### Alle Jobs auflisten
```
GET /api/jobs
GET /api/jobs?status=completed
```

### Konfiguration lesen
```
GET /api/config
```
Sensible Werte (API-Keys, Passwörter) werden automatisch maskiert.

### Konfiguration ändern
```
PATCH /api/config
Content-Type: application/json

{
    "reddit": {"thread": {"subreddit": "todayilearned"}},
    "settings": {"theme": "light"}
}
```

### Ergebnisse auflisten
```
GET /api/results
```

## n8n-Workflow-Beispiele

### Beispiel 1: Zeitgesteuerte Videogenerierung

Der mitgelieferte Workflow (`n8n/workflow_reddit_video_bot.json`) generiert alle 6 Stunden ein Video:

```
[Schedule Trigger] → [HTTP: POST /api/generate] → [Wait 2min] → [HTTP: GET /api/jobs/{id}]
                                                                          │
                                                                    ┌─────┴─────┐
                                                                    │  Fertig?   │
                                                                    ├─────┬─────┤
                                                                    Ja    Nein
                                                                    │      │
                                                            [Ergebnisse] [Warten & erneut prüfen]
```

### Beispiel 2: Webhook-Trigger

Erstelle einen Workflow, der über einen Webhook von außen ausgelöst wird:

1. **Webhook-Node** → Empfängt `POST` mit `{"subreddit": "AskReddit", "post_id": "xyz"}`
2. **HTTP Request** → `POST http://localhost:5000/api/generate` mit dem Body
3. **Wait-Node** → 2 Minuten warten
4. **HTTP Request** → `GET http://localhost:5000/api/jobs/{{job_id}}` (Status prüfen)
5. **IF-Node** → Prüfe ob `status == "completed"`
6. **Slack/Discord/E-Mail** → Benachrichtigung senden

### Beispiel 3: Mehrere Subreddits durchlaufen

1. **Schedule Trigger** → Täglicher Auslöser
2. **Code-Node** → Liste von Subreddits definieren:
   ```javascript
   return [
     { subreddit: "AskReddit" },
     { subreddit: "todayilearned" },
     { subreddit: "showerthoughts" }
   ];
   ```
3. **Loop** über jedes Subreddit:
   - **HTTP Request** → `POST /api/generate` mit jeweiligem Subreddit
   - **Wait** + **Status-Check**

### Beispiel 4: Mit YouTube-Upload kombinieren

1. Video generieren (wie oben)
2. **Read Binary File** → Video-Datei laden
3. **YouTube-Node** → Video hochladen mit Titel aus der API-Antwort

## Tipps

### Docker-Setup

Wenn du beides in Docker betreibst, verwende ein gemeinsames Netzwerk:

```yaml
# docker-compose.yml
services:
  n8n:
    image: n8nio/n8n
    ports:
      - "5678:5678"
    networks:
      - bot-network

  reddit-bot-api:
    build: .
    command: python api.py --host 0.0.0.0 --port 5000
    ports:
      - "5000:5000"
    volumes:
      - ./config.toml:/app/config.toml
      - ./results:/app/results
    networks:
      - bot-network

networks:
  bot-network:
    driver: bridge
```

In n8n verwendest du dann `http://reddit-bot-api:5000` statt `http://localhost:5000`.

### Fehlerbehandlung in n8n

- Aktiviere **"Continue on Fail"** bei HTTP-Request-Nodes
- Verwende einen **Error Trigger**-Workflow für Benachrichtigungen bei Fehlern
- Prüfe den `/api/health`-Endpunkt regelmäßig mit einem separaten Monitoring-Workflow

### Sicherheit

- Der API-Server hat **keine Authentifizierung** eingebaut. Setze ihn nur in vertrauenswürdigen Netzwerken ein oder stelle einen Reverse Proxy (nginx/Caddy) mit Basic Auth davor.
- Sensible Konfigurationswerte werden im `/api/config` GET-Endpunkt automatisch maskiert.

# Reddit Video Maker Bot in n8n nachbauen

Diese Anleitung erklärt Schritt für Schritt, wie du die komplette Video-Pipeline des Reddit Video Maker Bots direkt in n8n nachbaust.

## Architektur-Übersicht

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        n8n Workflow Pipeline                               │
│                                                                            │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐               │
│  │ Schedule  │──►│ Reddit   │──►│  Posts    │──►│Kommentare│               │
│  │ Trigger   │   │ OAuth    │   │ abrufen  │   │ abrufen  │               │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘               │
│                                                      │                     │
│                                                      ▼                     │
│                                               ┌──────────┐                │
│                                               │  Texte   │                │
│                                               │aufteilen │                │
│                                               └────┬─────┘                │
│                                                    │                       │
│                          ┌─────────────────────────┼──────────────┐       │
│                          ▼                         ▼              ▼       │
│                   ┌──────────┐              ┌──────────┐  ┌──────────┐   │
│                   │   TTS    │              │Screenshot│  │Background│   │
│                   │ (OpenAI) │              │(Playwrig)│  │(yt-dlp)  │   │
│                   └────┬─────┘              └────┬─────┘  └────┬─────┘   │
│                        │                         │              │         │
│                        └─────────────┬───────────┘──────────────┘         │
│                                      ▼                                     │
│                               ┌──────────┐                                │
│                               │  FFmpeg  │                                │
│                               │Composit. │                                │
│                               └────┬─────┘                                │
│                                    ▼                                       │
│                               ┌──────────┐                                │
│                               │  Fertiges│                                │
│                               │  Video   │                                │
│                               └──────────┘                                │
└────────────────────────────────────────────────────────────────────────────┘
```

## Voraussetzungen

Auf dem n8n-Server müssen installiert sein:

```bash
# Python + Playwright (für Screenshots)
pip install playwright mutagen
playwright install chromium

# FFmpeg (für Video-Komposition)
sudo apt install ffmpeg    # Ubuntu/Debian
brew install ffmpeg        # macOS

# yt-dlp (für Hintergrundvideos)
pip install yt-dlp
```

## Schritt 1: Credentials in n8n einrichten

### Reddit API Credentials

1. Gehe zu https://www.reddit.com/prefs/apps und erstelle eine **Script**-App
2. In n8n → **Credentials** → **New Credential** → **HTTP Basic Auth**:
   - **Name:** `Reddit API Credentials`
   - **User:** Deine Reddit App `client_id`
   - **Password:** Dein Reddit App `client_secret`
3. Speichere außerdem deinen Reddit **Username** und **Password** als Umgebungsvariablen:
   ```
   REDDIT_USERNAME=dein_username
   REDDIT_PASSWORD=dein_passwort
   ```

### OpenAI API Key (für TTS)

1. In n8n → **Credentials** → **New Credential** → **HTTP Header Auth**:
   - **Name:** `OpenAI API Key`
   - **Header Name:** `Authorization`
   - **Header Value:** `Bearer sk-dein-api-key`

## Schritt 2: Workflow importieren

1. Öffne n8n (`http://localhost:5678`)
2. **Workflows** → **Import from File**
3. Wähle `n8n/workflow_full_pipeline.json`
4. Der Workflow enthält 15 Nodes (alle auf Deutsch benannt)

## Schritt 3: Konfiguration anpassen

Öffne den Node **"Konfiguration"** und passe die Werte an:

```javascript
const config = {
  subreddit: 'AskReddit',      // Welches Subreddit
  theme: 'dark',                // dark oder light
  max_comment_length: 500,      // Max. Kommentarlänge
  min_comments: 20,             // Min. Kommentare pro Post
  width: 1080,                  // Video-Breite (px)
  height: 1920,                 // Video-Höhe (px)
  opacity: 0.9,                 // Screenshot-Transparenz
  bg_audio_volume: 0.15,        // Hintergrundmusik-Lautstärke
  tts_provider: 'openai',       // TTS-Anbieter
  openai_voice: 'alloy',        // Stimme (alloy, echo, nova, ...)
  openai_model: 'tts-1',        // Modell (tts-1, tts-1-hd)
  silence_duration: 0.3,        // Pause zwischen Kommentaren (Sek.)
};
```

## Schritt 4: Pfade anpassen

In den **Execute Command**-Nodes müssen die Pfade angepasst werden:

- **Node 11 (Screenshots):** Ändere `/path/to/RedditVideoMakerBot` zum tatsächlichen Pfad
- **Node 14 (Video zusammensetzen):** Ändere `/path/to/RedditVideoMakerBot` zum tatsächlichen Pfad

## Die 15 Nodes im Detail

### Node 1: Zeitplan (Schedule Trigger)
- **Typ:** Schedule Trigger
- **Intervall:** Alle 6 Stunden (anpassbar)
- Startet die Pipeline automatisch

### Node 2: Reddit OAuth Token (HTTP Request)
- **Methode:** `POST`
- **URL:** `https://www.reddit.com/api/v1/access_token`
- **Auth:** HTTP Basic Auth (client_id:client_secret)
- **Body:** `grant_type=password&username=...&password=...`
- **Ausgabe:** `access_token` für weitere API-Aufrufe

### Node 3: Posts abrufen (HTTP Request)
- **Methode:** `GET`
- **URL:** `https://oauth.reddit.com/r/{subreddit}/hot.json?limit=10`
- **Header:** `Authorization: Bearer {access_token}`
- Holt die heißesten Posts

### Node 4: Post auswählen (Code)
- Filtert Posts nach: genug Kommentare, kein NSFW, nicht angepinnt
- Wählt den ersten passenden Post
- Gibt Thread-ID, Titel, URL zurück

### Node 5: Kommentare abrufen (HTTP Request)
- **URL:** `https://oauth.reddit.com/comments/{thread_id}.json?limit=10&sort=top`
- Holt die Top-Kommentare

### Node 6: Kommentare verarbeiten (Code)
- Filtert gelöschte/entfernte Kommentare
- Prüft Mindest-/Maximallänge
- Strukturiert die Daten für die nächsten Schritte

### Node 7: Verzeichnisse anlegen (Execute Command)
- Erstellt `{work_dir}/audio/` und `{work_dir}/screenshots/`

### Node 8: Texte aufteilen (Code)
- Erstellt ein separates Item für den Titel und jeden Kommentar
- Jedes Item enthält den Text und die TTS-Konfiguration

### Node 9: TTS Audio generieren (Execute Command)
- Ruft die OpenAI TTS API auf (`POST /v1/audio/speech`)
- Speichert MP3-Dateien: `title.mp3`, `0.mp3`, `1.mp3`, ...
- Gibt die Audio-Dauer jeder Datei zurück

### Node 10: Dauern berechnen (Code)
- Berechnet Start-/Endzeiten für jedes Audio-Segment
- Berücksichtigt Pausen zwischen Kommentaren
- Erstellt die Timeline für die Video-Komposition

### Node 11: Dauern speichern (Execute Command)
- Schreibt `durations.json` für das FFmpeg-Skript

### Node 12: Screenshots erstellen (Execute Command)
- Ruft `screenshot_helper.py` auf
- Playwright öffnet Reddit, loggt sich ein, macht Screenshots
- Speichert: `title.png`, `comment_0.png`, `comment_1.png`, ...

### Node 13: Hintergrundvideo herunterladen (Execute Command)
- yt-dlp lädt Minecraft-Parkour-Video herunter
- FFmpeg schneidet einen zufälligen Abschnitt aus

### Node 14: Hintergrundmusik herunterladen (Execute Command)
- yt-dlp lädt Lofi-Musik herunter
- Schneidet auf die richtige Länge

### Node 15: Video zusammensetzen (Execute Command)
- Ruft `ffmpeg_compose.sh` auf
- Kombiniert: Hintergrund + Audio + Screenshot-Overlays
- Ausgabe: `{work_dir}/final.mp4`

## Alternative TTS-Anbieter

### ElevenLabs statt OpenAI

Ersetze den TTS-Command-Node mit:

```bash
curl -s 'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}' \
  -H 'xi-api-key: YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"text": "...", "model_id": "eleven_multilingual_v1"}' \
  -o output.mp3
```

### Google Translate TTS (kostenlos)

```bash
python3 -c "
from gtts import gTTS
tts = gTTS(text='Dein Text hier', lang='de', slow=False)
tts.save('output.mp3')
"
```

### TikTok TTS (kostenlos, benötigt Session-ID)

```bash
curl -s 'https://api16-normal-c-useast1a.tiktokv.com/media/api/text/speech/invoke/' \
  -H 'User-Agent: com.zhiliaoapp.musically/2022600030' \
  -H 'Cookie: sessionid=DEINE_SESSION_ID' \
  -d 'req_text=Dein+Text&speaker_map_type=0&aid=1233&text_speaker=en_us_001' \
  | python3 -c "import sys,json,base64; \
    d=json.load(sys.stdin); \
    open('output.mp3','wb').write(base64.b64decode(d['data']['v_str']))"
```

## Erweiterungsmöglichkeiten

### YouTube-Upload hinzufügen
Füge nach Node 15 einen **Google YouTube**-Node hinzu:
1. YouTube OAuth2-Credentials einrichten
2. Node: **YouTube** → **Upload Video**
3. Titel und Beschreibung aus den Workflow-Daten setzen

### Discord/Slack-Benachrichtigung
Füge einen **Discord**- oder **Slack**-Node hinzu, um nach dem Rendern eine Nachricht zu senden:
```
Neues Video fertig!
Subreddit: r/AskReddit
Titel: "Was ist euer bester Life-Hack?"
Dauer: 2:30
```

### Mehrere Subreddits
Verwende einen **Split In Batches**-Node vor dem OAuth-Node:
```javascript
return [
  { json: { subreddit: 'AskReddit' } },
  { json: { subreddit: 'todayilearned' } },
  { json: { subreddit: 'showerthoughts' } },
];
```

### Fehlerbehandlung
- Aktiviere **"Continue on Fail"** bei HTTP-Nodes
- Füge einen **Error Trigger**-Workflow hinzu
- Verwende **IF**-Nodes nach kritischen Schritten

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| Reddit 401 Error | OAuth-Credentials prüfen, Token abgelaufen? |
| Screenshots leer | Playwright installiert? `playwright install chromium` |
| FFmpeg nicht gefunden | `sudo apt install ffmpeg` oder Pfad prüfen |
| yt-dlp Fehler | `pip install --upgrade yt-dlp` |
| TTS Timeout | Text kürzen oder Timeout erhöhen |
| Video ohne Ton | Audio-Dateien prüfen: `ls {work_dir}/audio/` |

## Dateien

| Datei | Beschreibung |
|-------|-------------|
| `n8n/workflow_full_pipeline.json` | Vollständiger n8n-Workflow (15 Nodes) |
| `n8n/screenshot_helper.py` | Playwright-Skript für Reddit-Screenshots |
| `n8n/ffmpeg_compose.sh` | FFmpeg-Skript für Video-Komposition |
| `n8n/workflow_reddit_video_bot.json` | Einfacher API-basierter Workflow |

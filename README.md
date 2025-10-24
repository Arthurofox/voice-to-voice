# Local Voice Translator (EN ⇄ FR)

Local playground for OpenAI's latest speech capabilities:

- GPT-4o **Realtime** (WebRTC) for low-latency translation
- GPT-4o **Realtime-Mini** for cost-conscious streaming
- GPT **Audio (direct)** for audio-in → audio-out translation

Speak in English or French and hear the reply in the other language, all from your machine.

---

## Project structure

```
backend/
  main.py                 # FastAPI app with realtime token endpoint + audio translate route
  realtime_client_manager.py
  audio_translate.py
frontend/
  streamlit_app.py        # Streamlit UI
  static/realtime.html    # WebRTC client embedded in Streamlit or opened directly
.env.example
requirements.txt
```

---

## Prerequisites

1. **Python 3.10+** (3.11 recommended).
2. Recommended: create and activate a virtual environment.
3. Copy `.env.example` → `.env` and fill in the values:

   ```bash
   OPENAI_API_KEY=sk-your-key
   REALTIME_MODEL=gpt-realtime
   REALTIME_MINI_MODEL=gpt-4o-mini-realtime-preview
   AUDIO_MODEL=gpt-4o-mini
   DEFAULT_VOICE=verse
   BACKEND_URL=http://127.0.0.1:8000
   REALTIME_TRANSPORT=auto
   TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
   TTS_MODEL=gpt-4o-mini-tts
   ```

4. Install dependencies (run manually):

   ```bash
   pip install -r requirements.txt
   ```

5. Allow microphone access for `http://localhost` in your browser.

---

## Running the project

> These commands are **not** executed for you—run them manually in separate terminals.

1. **Start the backend (FastAPI)**  
   ```bash
   python -m uvicorn backend.main:app --reload
   ```
   - Health check: `http://127.0.0.1:8000/health`
   - Realtime token endpoint: `http://127.0.0.1:8000/realtime/token`
   - Transport self-test: `http://127.0.0.1:8000/realtime/self-test`
   - Audio translate endpoint: `http://127.0.0.1:8000/audio/translate`
   - Static realtime client: `http://127.0.0.1:8000/frontend/static/realtime.html`

2. **Start the frontend (Streamlit)**  
   ```bash
   streamlit run frontend/streamlit_app.py
   ```
   - Default URL: `http://127.0.0.1:8501`

---

## Using the app

1. Open the Streamlit page. Complete the first-run checklist to confirm setup.
2. Choose the **language direction** (EN→FR or FR→EN) and an output voice.
3. Pick a mode:
   - **Realtime (gpt-realtime) — WebRTC**  
     - Click *Connect (WebRTC)* → token minted via `/realtime/token`.  
     - Allow mic access.  
     - Speak and listen for the translated reply; metrics reflect offer/answer timing.
   - **Realtime-Mini — WebSocket**  
     - Click *Connect (WebSocket)* to attach to the local relay.  
     - Use *Start/Stop Speaking* to stream PCM to the OpenAI Realtime WS API.  
     - The widget auto-falls back here if you try WebRTC with the mini model.
   - **Audio (Direct)**  
     - Record a short clip (≤15 s).  
     - Backend pipeline: transcribe (`TRANSCRIPTION_MODEL`) → translate via `AUDIO_MODEL` → synthesize speech with `TTS_MODEL`.  
     - Streamlit auto-plays the returned WAV and shows per-stage latency.
4. Monitor latency numbers and recent events in the log panel (top-right).

Want to debug WebRTC separately? Open the static client directly in a browser tab:
`http://127.0.0.1:8000/frontend/static/realtime.html?source=en&target=fr&voice=verse&model=gpt-4o-realtime-preview`

---

## Troubleshooting

- **No audio or microphone prompt**  
  - Ensure the browser trusts `http://localhost` and the tab is focused.  
  - Headphones recommended to avoid echo loops.
- **Realtime token errors**  
  - Confirm `OPENAI_API_KEY` is correct and has access to the realtime preview.  
  - Try regenerating the token (Connect button).
- **Empty-body 400 after SDP POST**  
  - The selected model does not accept WebRTC. The widget will warn and fall back to the WebSocket relay automatically.
- **Opus playback issues**  
  - Some browsers struggle with Opus + WebRTC. Refresh the page; the widget can fall back to PCM/WAV when needed.
- **`audio/translate` request fails**  
  - Keep clips short (< 2 MB).  
  - Inspect backend logs for model errors; remember this route first transcribes, then translates, then runs TTS—failures from any stage surface here.
- **Cross-origin problems**  
  - Backend enables CORS for localhost:8000/8501. If you change ports, update the allowlist in `backend/main.py`.
- **Firewall/VPN interference**  
  - WebRTC uses UDP; restrictive networks can block STUN/TURN traffic. Disable VPN or allow UDP 3478.
- **ImportError: cannot import name 'OpenAI'**  
  - Ensure you're running inside the project venv (`which python` → `.../voice-to-voice/venv/bin/python`).  
  - Remove legacy SDKs: `pip uninstall -y openai openai-secret-manager`.  
  - Re-install: `pip install -U -r requirements.txt`.  
  - Verify: `python -c "import sys, openai; print(sys.executable); print(openai.__file__)"` should show paths inside the venv.

---

## Customisation

- Override default models/voice by editing `.env`.
- Update the voice list in `frontend/streamlit_app.py` to surface other options.
- Adjust the existing WebSocket relay in `backend/main.py` if you need to proxy additional headers or support new transports.
- Set `REALTIME_TRANSPORT` to `webrtc`, `websocket`, or `auto` if you want to force a specific transport irrespective of the model mapping.

---

## References

1. [OpenAI Realtime overview](https://platform.openai.com/docs/guides/realtime) — WebRTC support for `gpt-realtime` with streaming audio.  
2. [Azure/OpenAI realtime quickstart](https://learn.microsoft.com/azure/ai-services/openai/how-to/realtime) — highlights `gpt-4o-mini-realtime-preview` in the WebSocket flow.  
3. [OpenAI developer community thread](https://community.openai.com/t/170269) — empty HTTP 400 body indicates a transport mismatch; switching to the supported WebSocket path resolves the error.

Stay mindful: audio is kept in-memory only; no persistence or logging beyond console metrics. Keep your API key private—tokens are minted server-side so the key never reaches the browser.
- **Transport matrix sanity check**  
  | Model | Transport | Expected handshake | Manual test |
  | --- | --- | --- | --- |
  | `gpt-realtime` (default) | WebRTC | SDP POST → 200 OK | Speak “Bonjour” → hear English back; metrics show offer/answer times |
  | `gpt-4o-mini-realtime-preview` | WebSocket relay | WS upgrade → 101 Switching Protocols | Click *Start Speaking*, say “Hello” → hear French reply; WS messages include `response.audio.delta` |
  | Direct audio (`TRANSCRIPTION_MODEL` + `AUDIO_MODEL` + `TTS_MODEL`) | HTTP POST | 200 JSON with base64 WAV | Record ≤15 s clip, confirm translated WAV plays and logs list transcription/translation/TTS timings |

  Quick verification steps:
  1. **WebRTC:** Connect in Streamlit, speak “Bonjour”, confirm audio reply and metrics populate. Browser devtools should show `POST /v1/realtime?model=gpt-realtime` returning 200.
  2. **WebSocket:** Switch to *Realtime-Mini*, click *Start Speaking*, say “Hello”. Network tab should show `wss://api.openai.com/v1/realtime?...` upgraded via the local relay with incoming `response.audio.delta`.
  3. **HTTP direct:** Use the Audio panel, record ≤15 s, send, and play back returned audio. The timings block should list total latency.

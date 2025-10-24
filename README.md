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
   REALTIME_MODEL=gpt-4o-realtime-preview
   REALTIME_MINI_MODEL=gpt-4o-realtime-mini
   AUDIO_MODEL=gpt-4o-audio-preview
   DEFAULT_VOICE=verse
   BACKEND_URL=http://127.0.0.1:8000
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
   - **Realtime (4o)**  
     - Click *Connect* → token minted via `/realtime/token`.  
     - Allow mic access.  
     - Speak; the server streams translated speech back immediately.
   - **Realtime-Mini**  
     - Same flow but uses `gpt-4o-realtime-mini` for lower-cost runs.
   - **Audio (Direct)**  
     - Record a short clip (≤15 s).  
     - Send it to `/audio/translate` and play the synthesized translation.
4. Monitor latency numbers and recent events in the log panel.

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
- **Opus playback issues**  
  - Some browsers struggle with Opus + WebRTC. Refresh the page; the widget can fall back to PCM/WAV when needed.
- **`audio/translate` request fails**  
  - Keep clips short (< 2 MB).  
  - Inspect backend logs for model/voice errors.
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
- To add a websocket relay, expand `backend/main.py` with a `/relay` endpoint (left out by default for simplicity).

Stay mindful: audio is kept in-memory only; no persistence or logging beyond console metrics. Keep your API key private—tokens are minted server-side so the key never reaches the browser.

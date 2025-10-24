import base64
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components
from audio_recorder_streamlit import audio_recorder


BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
REALTIME_STATIC_URL = f"{BACKEND_URL}/frontend/static/realtime.html"

VOICES = [
    ("verse", "Verse (default)"),
    ("alloy", "Alloy"),
    ("aria", "Aria"),
]

LANGUAGE_OPTIONS = {
    "EN → FR": ("en", "fr"),
    "FR → EN": ("fr", "en"),
}


def append_log(message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    logs: List[Dict[str, Any]] = st.session_state.setdefault("logs", [])
    logs.append(
        {
            "timestamp": dt.datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "payload": payload or {},
        }
    )
    st.session_state["logs"] = logs[-10:]


def fetch_realtime_token(model: str, source: str, target: str, voice: str) -> Dict[str, Any]:
    params = {
        "model": model,
        "source_lang": source,
        "target_lang": target,
        "voice": voice,
    }
    response = requests.get(f"{BACKEND_URL}/realtime/token", params=params, timeout=15)
    response.raise_for_status()
    token = response.json()
    append_log("Realtime token issued", {"model": model, "expires": token.get("expires_at")})
    return token


def render_logs() -> None:
    st.subheader("Event Log")
    logs: List[Dict[str, Any]] = st.session_state.get("logs", [])
    if not logs:
        st.info("No events yet. Interact with the translator to see live updates.")
        return
    for entry in reversed(logs):
        st.write(f"[{entry['timestamp']}] {entry['message']}")
        if entry["payload"]:
            st.caption(json.dumps(entry["payload"], indent=2))


def ensure_preflight_checklist() -> None:
    if st.session_state.get("preflight_checked"):
        return

    with st.expander("First-run checklist (required)", expanded=True):
        st.markdown(
            "- Python 3.10+ recommended with an active virtualenv.\n"
            "- Dependencies installed via `pip install -r requirements.txt`.\n"
            "- `.env` contains your `OPENAI_API_KEY`.\n"
            "- Browser mic permissions allowed for localhost.\n"
            "- Backend running: `uvicorn backend.main:app --reload`.\n"
            "- Streamlit running: `streamlit run frontend/streamlit_app.py`."
        )
        acknowledged = st.checkbox("I have completed the setup above.")
        if acknowledged:
            st.session_state["preflight_checked"] = True
            append_log("Prerequisites confirmed by user")


def main() -> None:
    st.set_page_config(page_title="Local Voice Translator", layout="wide")
    st.title("Local Voice Translator (EN ⇄ FR)")
    st.caption("Compare GPT-4o Realtime, Realtime-Mini, and direct audio translation locally.")

    ensure_preflight_checklist()

    selected_direction = st.radio("Language direction", list(LANGUAGE_OPTIONS.keys()))
    source_lang, target_lang = LANGUAGE_OPTIONS[selected_direction]

    voice_options = [label for _, label in VOICES]
    selected_voice_label = st.selectbox("Output voice", voice_options, index=0)
    selected_voice = next(code for code, label in VOICES if label == selected_voice_label)

    mode = st.radio(
        "Mode",
        ("Realtime (4o)", "Realtime-Mini", "Audio (Direct)"),
        help="Select a translation path to test.",
    )

    if mode in ("Realtime (4o)", "Realtime-Mini"):
        realtime_model = (
            os.environ.get("REALTIME_MODEL", "gpt-4o-realtime-preview")
            if mode == "Realtime (4o)"
            else os.environ.get("REALTIME_MINI_MODEL", "gpt-4o-realtime-mini")
        )

        st.markdown(
            "1. Click **Connect** to mint an ephemeral token.\n"
            "2. Allow microphone access when prompted.\n"
            "3. Speak in the source language and listen for the translated reply.\n"
            "If Opus fails, refresh and choose PCM in the realtime widget."
        )

        token_container = st.empty()
        connect_col, disconnect_col = st.columns(2)

        if connect_col.button("Connect to Realtime", type="primary"):
            try:
                token = fetch_realtime_token(realtime_model, source_lang, target_lang, selected_voice)
                st.session_state["realtime_session"] = token
                token_container.success(
                    f"Token ready for {realtime_model}. Expires at {token.get('expires_at', 'soon')}."
                )
            except requests.HTTPError as exc:
                st.error(f"Failed to fetch token: {exc.response.text}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Token request failed: {exc}")

        if disconnect_col.button("Disconnect"):
            st.session_state.pop("realtime_session", None)
            token_container.info("Realtime session reset. Generate a new token to reconnect.")
            append_log("Realtime session cleared")

        token = st.session_state.get("realtime_session")
        if token and token.get("client_secret"):
            params = (
                f"source={source_lang}&target={target_lang}"
                f"&voice={selected_voice}&model={realtime_model}"
            )
            iframe_src = f"{REALTIME_STATIC_URL}?{params}#token={token['client_secret']}"
            iframe_html = (
                f'<iframe src="{iframe_src}" width="100%" height="580" frameborder="0" '
                'allow="microphone; autoplay; clipboard-write"></iframe>'
            )
            components.html(iframe_html, height=600)
            st.info(
                "Keep this tab focused to reduce audio glitches. Latency stats will appear inside the realtime widget."
            )
        else:
            st.warning("Mint a realtime token to start streaming.")

    elif mode == "Audio (Direct)":
        st.markdown(
            "Record a short utterance (≤15 seconds). When you release the record button, a WAV clip "
            "is produced and can be sent for translation."
        )

        audio_bytes = audio_recorder(
            text="Tap to record / tap again to stop",
            recording_color="#e07a5f",
            neutral_color="#3d405b",
            icon_name="microphone",
        )

        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            st.success("Clip captured. Click translate to send it to the backend.")

            if st.button("Translate clip", type="primary"):
                append_log("Sending audio clip to backend", {"mode": "audio_direct"})
                files = {"audio_file": ("recording.wav", audio_bytes, "audio/wav")}
                params = {
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "voice": selected_voice,
                }
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/audio/translate",
                        params=params,
                        files=files,
                        timeout=90,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    translation_audio = base64.b64decode(payload["audio_base64"])
                    st.audio(translation_audio, format="audio/wav")
                    st.success(
                        f"Translated audio ready using voice `{payload.get('voice')}` "
                        f"and model `{payload.get('model')}`."
                    )

                    timing = payload.get("timing", {})
                    st.json(
                        {
                            "Total latency (ms)": round(timing.get("total_latency_ms", 0), 1),
                            "Request duration (ms)": round(timing.get("request_duration_ms", 0), 1),
                            "Detected source language": payload.get("detected_source_language"),
                        }
                    )
                    append_log("Audio translation completed", timing)
                except requests.HTTPError as exc:
                    st.error(f"Translation failed: {exc.response.text}")
                    append_log("Audio translation failed", {"status": exc.response.status_code})
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Unexpected error: {exc}")
                    append_log("Audio translation failed", {"error": str(exc)})
        else:
            st.info("Idle. Tap the record button above to capture audio.")

    render_logs()


if __name__ == "__main__":
    main()

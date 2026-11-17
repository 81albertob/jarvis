import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Jarvis", page_icon="🤖")
st.title("🤖 J.A.R.V.I.S.")

# --- Protezione con password ---
if "ok" not in st.session_state:
    st.session_state.ok = False

if not st.session_state.ok:
    pwd = st.text_input("Password", type="password")
    if pwd:
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.ok = True
            st.rerun()
        else:
            st.error("Password errata")
    st.stop()

# --- Collegamento al cervello ---
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"].strip())
MODEL = "gemini-3.1-flash-lite"

ISTRUZIONI = (
    "Sei Jarvis, un assistente personale elegante, ironico e molto competente, "
    "come quello di Tony Stark. Rispondi sempre in italiano, in modo chiaro e conciso. "
    "Quando serve, cerca informazioni aggiornate online."
)

# --- Cronologia della chat ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["text"])

prompt = st.chat_input("Parla con Jarvis...")

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    contenuti = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["text"])],
        )
        for m in st.session_state.messages
    ]

    with st.chat_message("assistant"):
        with st.spinner("Elaboro..."):
            try:
                risposta = client.models.generate_content(
                    model=MODEL,
                    contents=contenuti,
                    config=types.GenerateContentConfig(
                        system_instruction=ISTRUZIONI,
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                testo = risposta.text or "Non ho ricevuto risposta."
            except Exception as e:
                testo = "ERRORE: " + str(e)[:500]
        st.markdown(testo)

    st.session_state.messages.append({"role": "assistant", "text": testo})

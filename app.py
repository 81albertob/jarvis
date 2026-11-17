import datetime
import streamlit as st
from google import genai
from google.genai import types
from ddgs import DDGS

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

oggi = datetime.date.today().strftime("%d/%m/%Y")
ISTRUZIONI = (
    "Sei Jarvis, un assistente personale elegante, ironico e molto competente, "
    "come quello di Tony Stark. Rispondi sempre in italiano, in modo chiaro e conciso. "
    f"La data di oggi è {oggi}. "
    "Se ti vengono forniti risultati di ricerca web, usali e cita le fonti."
)

# --- Interruttore ricerca online ---
usa_web = st.sidebar.checkbox("🔎 Ricerca online", value=True)


def cerca_web(domanda):
    try:
        risultati = DDGS().text(domanda, region="it-it", max_results=5)
        return "\n".join(
            f"- {r['title']}: {r['body']} ({r['href']})" for r in risultati
        )
    except Exception:
        return ""


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

    testo_per_ai = prompt
    if usa_web:
        with st.spinner("Cerco online..."):
            info = cerca_web(prompt)
        if info:
            testo_per_ai = (
                prompt
                + "\n\n[Risultati di ricerca web aggiornati]\n"
                + info
            )

    contenuti = []
    ultimo = len(st.session_state.messages) - 1
    for i, m in enumerate(st.session_state.messages):
        testo_msg = testo_per_ai if i == ultimo else m["text"]
        contenuti.append(
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=testo_msg)],
            )
        )

    with st.chat_message("assistant"):
        with st.spinner("Elaboro..."):
            try:
                risposta = client.models.generate_content(
                    model=MODEL,
                    contents=contenuti,
                    config=types.GenerateContentConfig(
                        system_instruction=ISTRUZIONI,
                    ),
                )
                testo = risposta.text or "Non ho ricevuto risposta."
            except Exception as e:
                testo = "ERRORE: " + str(e)[:500]
        st.markdown(testo)

    st.session_state.messages.append({"role": "assistant", "text": testo})

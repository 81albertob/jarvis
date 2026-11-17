import datetime
import requests
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

# --- Collegamento al database (Supabase) ---
DB_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/") + "/rest/v1/"
DB_KEY = st.secrets["SUPABASE_KEY"].strip()
DB_HEADERS = {"apikey": DB_KEY, "Content-Type": "application/json"}
if DB_KEY.startswith("eyJ"):
    DB_HEADERS["Authorization"] = "Bearer " + DB_KEY


def db_leggi(tabella, params):
    r = requests.get(DB_URL + tabella, headers=DB_HEADERS, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def db_scrivi(tabella, dati):
    h = dict(DB_HEADERS, Prefer="return=minimal")
    r = requests.post(DB_URL + tabella, headers=h, json=dati, timeout=10)
    r.raise_for_status()


def db_cancella(tabella, params):
    r = requests.delete(DB_URL + tabella, headers=DB_HEADERS, params=params, timeout=10)
    r.raise_for_status()


def carica_memorie():
    return db_leggi("memorie", {"select": "id,testo", "order": "id"})


def carica_chat():
    righe = db_leggi(
        "chat", {"select": "ruolo,testo", "order": "id.desc", "limit": "30"}
    )
    righe.reverse()
    while righe and righe[0]["ruolo"] != "user":
        righe.pop(0)
    return [{"role": r["ruolo"], "text": r["testo"]} for r in righe]


def salva_chat(ruolo, testo):
    if st.session_state.db_ok:
        try:
            db_scrivi("chat", {"ruolo": ruolo, "testo": testo})
        except Exception:
            pass


# --- Primo caricamento: memoria e cronologia ---
if "db_ok" not in st.session_state:
    try:
        st.session_state.memorie = carica_memorie()
        st.session_state.messages = carica_chat()
        st.session_state.db_ok = True
        st.session_state.db_errore = ""
    except Exception as e:
        st.session_state.memorie = []
        st.session_state.messages = []
        st.session_state.db_ok = False
        st.session_state.db_errore = str(e)[:300]

# --- Menu laterale ---
st.sidebar.header("Jarvis")
usa_web = st.sidebar.checkbox("🔎 Ricerca online", value=True)

if st.session_state.db_ok:
    st.sidebar.success("🧠 Memoria collegata")
else:
    st.sidebar.error("Memoria NON collegata: " + st.session_state.db_errore)

with st.sidebar.expander("Cosa ricordo di te"):
    if not st.session_state.memorie:
        st.write("Ancora niente. Scrivi: ricorda che ...")
    for mem in st.session_state.memorie:
        if st.button("🗑 " + mem["testo"][:40], key="del" + str(mem["id"])):
            try:
                db_cancella("memorie", {"id": "eq." + str(mem["id"])})
                st.session_state.memorie = carica_memorie()
            except Exception:
                pass
            st.rerun()

if st.sidebar.button("Cancella cronologia chat"):
    try:
        db_cancella("chat", {"id": "gt.0"})
    except Exception:
        pass
    st.session_state.messages = []
    st.rerun()

# --- Istruzioni per Jarvis (con le cose che ricorda) ---
oggi = datetime.date.today().strftime("%d/%m/%Y")
ISTRUZIONI = (
    "Sei Jarvis, un assistente personale elegante, ironico e molto competente, "
    "come quello di Tony Stark. Rispondi sempre in italiano, in modo chiaro e conciso. "
    f"La data di oggi è {oggi}. "
    "Se ti vengono forniti risultati di ricerca web, usali e cita le fonti."
)
if st.session_state.memorie:
    ISTRUZIONI += "\n\nCose che sai sull'utente (memoria permanente):\n" + "\n".join(
        "- " + m["testo"] for m in st.session_state.memorie
    )


def cerca_web(domanda):
    try:
        risultati = DDGS().text(domanda, region="it-it", max_results=5)
        return "\n".join(
            f"- {r['title']}: {r['body']} ({r['href']})" for r in risultati
        )
    except Exception:
        return ""


# --- Mostra la chat ---
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["text"])

prompt = st.chat_input("Parla con Jarvis...")

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    salva_chat("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Comando "ricorda ..."
    if prompt.lower().startswith("ricorda"):
        fatto = prompt[7:].strip(" :,-")
        if fatto and st.session_state.db_ok:
            try:
                db_scrivi("memorie", {"testo": fatto})
                st.session_state.memorie = carica_memorie()
                testo = "Annotato: " + fatto
            except Exception as e:
                testo = "ERRORE nel salvare: " + str(e)[:300]
        else:
            testo = "Cosa devo ricordare? Scrivi ad esempio: ricorda che ..."
        with st.chat_message("assistant"):
            st.markdown(testo)
        st.session_state.messages.append({"role": "assistant", "text": testo})
        salva_chat("assistant", testo)
        st.stop()

    testo_per_ai = prompt
    if usa_web:
        with st.spinner("Cerco online..."):
            info = cerca_web(prompt)
        if info:
            testo_per_ai = (
                prompt + "\n\n[Risultati di ricerca web aggiornati]\n" + info
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
    salva_chat("assistant", testo)

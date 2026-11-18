import datetime
import re
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from google import genai
from google.genai import types
from ddgs import DDGS
from icalendar import Calendar
import recurring_ical_events

st.set_page_config(page_title="Jarvis", page_icon="🤖")
st.title("🤖 J.A.R.V.I.S.")

FUSO = ZoneInfo("Europe/Rome")
MODELLI = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

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


# --- Calendario (sola lettura) ---
@st.cache_data(ttl=300, show_spinner=False)
def leggi_calendario(url, giorni=14):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        inizio = datetime.datetime.now(FUSO).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fine = inizio + datetime.timedelta(days=giorni)
        eventi = recurring_ical_events.of(cal).between(inizio, fine)
        elenco = []
        for e in eventi:
            if str(e.get("STATUS", "")).upper() == "CANCELLED":
                continue
            dt = e.get("DTSTART").dt
            if isinstance(dt, datetime.datetime):
                if dt.tzinfo:
                    dt = dt.astimezone(FUSO)
                quando = dt.strftime("%d/%m/%Y %H:%M")
                chiave = dt.strftime("%Y-%m-%d %H:%M")
            else:
                quando = dt.strftime("%d/%m/%Y") + " (tutto il giorno)"
                chiave = dt.strftime("%Y-%m-%d") + " 00:00"
            titolo = str(e.get("SUMMARY", "Senza titolo"))[:80]
            elenco.append((chiave, quando + " - " + titolo))
        elenco.sort()
        return [x[1] for x in elenco[:40]], ""
    except Exception as ex:
        return [], str(ex).replace(url, "[indirizzo]")[:200]


CAL_URL = str(st.secrets.get("CALENDAR_URL", "")).strip()
if CAL_URL:
    eventi_cal, errore_cal = leggi_calendario(CAL_URL)
else:
    eventi_cal, errore_cal = [], "non configurato"

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

if CAL_URL and not errore_cal:
    st.sidebar.success("📅 Calendario collegato (" + str(len(eventi_cal)) + " eventi)")
elif CAL_URL:
    st.sidebar.error("Calendario NON collegato: " + errore_cal)
else:
    st.sidebar.info("📅 Calendario non configurato")

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

# --- Istruzioni per Jarvis ---
adesso = datetime.datetime.now(FUSO)
oggi = GIORNI[adesso.weekday()] + " " + adesso.strftime("%d/%m/%Y %H:%M")
ISTRUZIONI = (
    "Sei Jarvis, un assistente personale elegante, ironico e molto competente, "
    "come quello di Tony Stark. Rispondi sempre in italiano, in modo chiaro e conciso. "
    f"Data e ora attuali (Italia): {oggi}. "
    "Non dire mai di aver salvato o annotato qualcosa: lo fa un comando a parte. "
    "Dai del tu all'utente. "
    "Se ti vengono forniti risultati di ricerca web, usali e cita le fonti."
)
if st.session_state.memorie:
    ISTRUZIONI += "\n\nCose che sai sull'utente (memoria permanente):\n" + "\n".join(
        "- " + m["testo"] for m in st.session_state.memorie
    )
if CAL_URL and not errore_cal:
    if eventi_cal:
        ISTRUZIONI += (
            "\n\nAppuntamenti dell'utente nei prossimi 14 giorni (dal suo calendario):\n"
            + "\n".join("- " + x for x in eventi_cal)
        )
    else:
        ISTRUZIONI += "\n\nL'utente non ha appuntamenti nei prossimi 14 giorni."


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

    # Comando "ricorda ..." (anche in mezzo alla frase)
    trovato = re.search(r"\bricord(a|ati)\b", prompt, flags=re.IGNORECASE)
    if trovato:
        fatto = prompt[trovato.end():].strip(" :,-")
        for p in ("ti ", "mi ", "che ", "di "):
            if fatto.lower().startswith(p):
                fatto = fatto[len(p):]
        fatto = fatto.strip(" :,-")
        if fatto and st.session_state.db_ok:
            try:
                db_scrivi("memorie", {"testo": fatto})
                st.session_state.memorie = carica_memorie()
                testo = "Annotato: " + fatto
            except Exception as e:
                testo = "ERRORE nel salvare: " + str(e)[:300]
        else:
            testo = "Cosa devo ricordare? Scrivi ad esempio: ricorda che ..."
        st.session_state.messages.append({"role": "assistant", "text": testo})
        salva_chat("assistant", testo)
        st.rerun()

    # Ricerca web (non serve per domande sul calendario)
    parole_calendario = ("appuntament", "calendario", "agenda", "impegn")
    parla_di_calendario = any(p in prompt.lower() for p in parole_calendario)
    testo_per_ai = prompt
    if usa_web and not parla_di_calendario:
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
            testo = None
            ultimo_errore = ""
            for nome_modello in MODELLI:
                try:
                    risposta = client.models.generate_content(
                        model=nome_modello,
                        contents=contenuti,
                        config=types.GenerateContentConfig(
                            system_instruction=ISTRUZIONI,
                        ),
                    )
                    testo = risposta.text
                    if testo:
                        break
                except Exception as e:
                    ultimo_errore = str(e)[:300]
            if not testo:
                if ultimo_errore:
                    testo = "ERRORE: " + ultimo_errore
                else:
                    testo = "Non ho ricevuto risposta."
        st.markdown(testo)

    st.session_state.messages.append({"role": "assistant", "text": testo})
    salva_chat("assistant", testo)

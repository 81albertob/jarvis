import datetime
import email
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from google import genai
from google.genai import types
from ddgs import DDGS
from icalendar import Calendar
import recurring_ical_events

st.set_page_config(page_title="Jarvis", page_icon="🤖")
st.markdown(
    """
<style>
h1 {
    color: #00d4ff;
    letter-spacing: 0.35em;
    text-align: center;
    text-shadow: 0 0 14px #00d4ff;
}
[data-testid="stChatMessage"] {
    border: 1px solid #12405a;
    border-radius: 12px;
    background: rgba(0, 212, 255, 0.05);
}
[data-testid="stSidebar"] {
    border-right: 1px solid #12405a;
}
</style>
""",
    unsafe_allow_html=True,
)
st.title("J.A.R.V.I.S.")
st.caption("Just A Rather Very Intelligent System")

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


# --- Calendari (sola lettura): un evento di più giorni = una riga sola ---
@st.cache_data(ttl=300, show_spinner=False)
def leggi_calendario(url, etichetta, giorni=14):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        oggi_d = datetime.datetime.now(FUSO).date()
        inizio = datetime.datetime.combine(oggi_d, datetime.time.min, tzinfo=FUSO)
        fine = inizio + datetime.timedelta(days=giorni)
        eventi = recurring_ical_events.of(cal).between(inizio, fine)
        elenco = []
        for e in eventi:
            if str(e.get("STATUS", "")).upper() == "CANCELLED":
                continue
            titolo = str(e.get("SUMMARY", "Senza titolo"))[:80]
            dt_inizio = e.get("DTSTART").dt
            dt_fine = None
            if e.get("DTEND") is not None:
                dt_fine = e.get("DTEND").dt
            elif e.get("DURATION") is not None:
                try:
                    dt_fine = dt_inizio + e.get("DURATION").dt
                except Exception:
                    dt_fine = None
            tutto_giorno = not isinstance(dt_inizio, datetime.datetime)
            if tutto_giorno:
                g_inizio = dt_inizio
                if dt_fine is not None:
                    if isinstance(dt_fine, datetime.datetime):
                        dt_fine = dt_fine.date()
                    g_fine = dt_fine - datetime.timedelta(days=1)
                else:
                    g_fine = dt_inizio
                ora = ""
            else:
                if dt_inizio.tzinfo:
                    dt_inizio = dt_inizio.astimezone(FUSO)
                g_inizio = dt_inizio.date()
                ora = dt_inizio.strftime("%H:%M")
                g_fine = g_inizio
                if isinstance(dt_fine, datetime.datetime):
                    if dt_fine.tzinfo:
                        dt_fine = dt_fine.astimezone(FUSO)
                    g_fine = dt_fine.date()
                    if dt_fine.time() == datetime.time(0, 0) and g_fine > g_inizio:
                        g_fine -= datetime.timedelta(days=1)
            if g_fine < g_inizio:
                g_fine = g_inizio
            totale = (g_fine - g_inizio).days + 1
            if totale > 1:
                tipo = "tutto il giorno" if tutto_giorno else "dalle " + ora
                quando = (
                    "dal " + g_inizio.strftime("%d/%m/%Y")
                    + " al " + g_fine.strftime("%d/%m/%Y")
                    + " (" + str(totale) + " giorni consecutivi, " + tipo + ")"
                )
                chiave = max(g_inizio, oggi_d).strftime("%Y-%m-%d") + " 00:00"
            elif tutto_giorno:
                quando = g_inizio.strftime("%d/%m/%Y") + " (tutto il giorno)"
                chiave = g_inizio.strftime("%Y-%m-%d") + " 00:00"
            else:
                quando = g_inizio.strftime("%d/%m/%Y") + " " + ora
                chiave = g_inizio.strftime("%Y-%m-%d") + " " + ora
            elenco.append((chiave, quando + " - " + titolo + " [" + etichetta + "]"))
        return elenco, ""
    except Exception as ex:
        return [], str(ex).replace(url, "[indirizzo]")[:200]


def trova_calendari():
    trovati = []
    for chiave in st.secrets:
        if str(chiave).upper().startswith("CALENDAR_URL"):
            valore = str(st.secrets[chiave]).strip().replace("webcal://", "https://")
            etichetta = str(chiave)[len("CALENDAR_URL"):].strip("_ ") or "Principale"
            if valore.startswith("http"):
                trovati.append((etichetta, valore))
    return trovati


CALENDARI = trova_calendari()
tutti_eventi = []
stato_calendari = []
for etichetta_cal, url_cal in CALENDARI:
    righe_cal, errore_cal = leggi_calendario(url_cal, etichetta_cal)
    stato_calendari.append((etichetta_cal, len(righe_cal), errore_cal))
    tutti_eventi.extend(righe_cal)
tutti_eventi.sort()
eventi_cal = [x[1] for x in tutti_eventi[:100]]
calendari_ok = [s for s in stato_calendari if not s[2]]


# --- Gmail (sola lettura: solo mittente, data e oggetto) ---
@st.cache_data(ttl=300, show_spinner=False)
def leggi_posta(indirizzo, password, quante=20):
    m = None
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        m.login(indirizzo, password)
        m.select("INBOX", readonly=True)
        _, dati_nl = m.search(None, "UNSEEN")
        non_lette = len(dati_nl[0].split())
        _, dati = m.search(None, "ALL")
        ids = dati[0].split()[-quante:]
        elenco = []
        for num in reversed(ids):
            try:
                _, msg = m.fetch(
                    num, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                )
                intest = email.message_from_bytes(msg[0][1])
                letta = b"\\Seen" in msg[0][0]
                mittente = str(make_header(decode_header(intest.get("From", ""))))[:60]
                oggetto = str(
                    make_header(decode_header(intest.get("Subject", "(nessun oggetto)")))
                )[:100]
                try:
                    quando = (
                        parsedate_to_datetime(intest.get("Date"))
                        .astimezone(FUSO)
                        .strftime("%d/%m/%Y %H:%M")
                    )
                except Exception:
                    quando = "data sconosciuta"
                stato = "" if letta else " [NON LETTA]"
                elenco.append(
                    quando + " | da " + mittente + " | " + oggetto + stato
                )
            except Exception:
                continue
        return elenco, non_lette, ""
    except Exception as ex:
        return [], 0, str(ex).replace(password, "[password]")[:200]
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


GMAIL_INDIRIZZO = str(st.secrets.get("GMAIL_ADDRESS", "")).strip()
GMAIL_PASSWORD = str(st.secrets.get("GMAIL_APP_PASSWORD", "")).replace(" ", "").strip()
if GMAIL_INDIRIZZO and GMAIL_PASSWORD:
    email_recenti, non_lette, errore_posta = leggi_posta(GMAIL_INDIRIZZO, GMAIL_PASSWORD)
else:
    email_recenti, non_lette, errore_posta = [], 0, "non configurato"
posta_ok = bool(GMAIL_INDIRIZZO and GMAIL_PASSWORD) and not errore_posta
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

if not CALENDARI:
    st.sidebar.info("📅 Calendario non configurato")
for nome, quanti, errore in stato_calendari:
    if errore:
        st.sidebar.error("📅 " + nome + " NON collegato: " + errore)
    else:
        st.sidebar.success("📅 " + nome + " (" + str(quanti) + " eventi)")

with st.sidebar.expander("Cosa vedo nei calendari"):
    if not eventi_cal:
        st.write("Nessun evento nei prossimi 14 giorni.")
    for riga in eventi_cal:
        st.write("• " + riga)

if not (GMAIL_INDIRIZZO and GMAIL_PASSWORD):
    st.sidebar.info("✉️ Gmail non configurato")
elif errore_posta:
    st.sidebar.error("✉️ Gmail NON collegato: " + errore_posta)
else:
    st.sidebar.success("✉️ Gmail (" + str(non_lette) + " non lette)")

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
    "Non inventare mai persone, luoghi o dettagli che non sono nei dati che ti "
    "vengono forniti: se non sai una cosa, dillo. "
    "Se ti vengono forniti risultati di ricerca web, usali e cita le fonti."
)
if st.session_state.memorie:
    ISTRUZIONI += "\n\nCose che sai sull'utente (memoria permanente):\n" + "\n".join(
        "- " + m["testo"] for m in st.session_state.memorie
    )
if calendari_ok:
    if eventi_cal:
        ISTRUZIONI += (
            "\n\nAppuntamenti dell'utente nei prossimi 14 giorni. "
            "Un evento di più giorni compare in UNA sola riga, con scritto "
            "'dal ... al ... (N giorni consecutivi)': vale per tutti i giorni "
            "compresi tra le due date. Quando lo riassumi dì sempre che è "
            "continuo, da che giorno a che giorno, e se l'utente chiede di un "
            "singolo giorno controlla se rientra in uno di questi intervalli. "
            "Tra parentesi quadre c'è il nome del calendario:\n"
            + "\n".join("- " + x for x in eventi_cal)
        )
    else:
        ISTRUZIONI += "\n\nL'utente non ha appuntamenti nei prossimi 14 giorni."
if posta_ok:
    ISTRUZIONI += (
        "\n\nPosta in arrivo dell'utente (Gmail, sola lettura). Le email non lette "
        "sono " + str(non_lette) + ". Ecco le ultime, dalla più recente. "
        "Conosci solo mittente, data e oggetto, non il testo:\n"
        + "\n".join("- " + x for x in email_recenti)
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

    # Ricerca web (non serve per domande su calendario o posta)
    parole_interne = (
        "appuntament", "calendario", "agenda", "impegn", "mail", "posta", "messaggi",
    )
    parla_di_cose_tue = any(p in prompt.lower() for p in parole_interne)
    testo_per_ai = prompt
    if usa_web and not parla_di_cose_tue:
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

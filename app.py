import datetime
import re
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
usa_web =

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
DB_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/") +

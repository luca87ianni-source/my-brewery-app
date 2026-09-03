import streamlit as st
import pandas as pd
import os
import math
import json
from datetime import date
from fpdf import FPDF 
from google import genai
from google.genai import types

# --- CARICAMENTO API KEY GEMINI (MODALITÀ SICURA) ---
def get_api_key():
    # 1. Prova a leggere dai Secrets di Streamlit (per il Cloud)
    if "GOOGLE_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_API_KEY"]
    
    # 2. Backup per il locale: se hai ancora il file .txt lo legge, 
    # altrimenti cerca nelle variabili d'ambiente
    if os.path.exists("key_gemini.txt"):
        with open("key_gemini.txt", "r") as f:
            return f.read().strip()
            
    return os.environ.get("GOOGLE_API_KEY", None)

api_key = get_api_key()

if api_key:
    client = genai.Client(api_key=api_key)
    st.session_state["api_key_configured"] = True
else:
    client = None
    st.error("Chiave API non trovata! Configura i Secrets su Streamlit o il file key_gemini.txt in locale.")

# --- 1. INIZIALIZZAZIONE SESSION STATE ---
if 'pagina' not in st.session_state: st.session_state.pagina = "Home"
if 'chat_history' not in st.session_state: st.session_state.chat_history = [] # Memoria Agente AI
if 'nome_b' not in st.session_state: st.session_state.nome_b = "Nuova Ricetta"
if 'stile_b' not in st.session_state: st.session_state.stile_b = ""
if 'data_imb' not in st.session_state: st.session_state.data_imb = date.today()
if 'litri_f' not in st.session_state: st.session_state.litri_f = 25.0
if 'litri_precedenti' not in st.session_state: st.session_state.litri_precedenti = 25.0 # Per monitorare i cambi
if 'f_list' not in st.session_state: st.session_state.f_list = []
if 'l_list' not in st.session_state: st.session_state.l_list = []
if 'm_list' not in st.session_state: st.session_state.m_list = []
if 'yeast_sel' not in st.session_state: st.session_state.yeast_sel = None
if 'og_reale' not in st.session_state: st.session_state.og_reale = 1.050
if 'fg_reale' not in st.session_state: st.session_state.fg_reale = 1.010
if 'abv_reale' not in st.session_state: st.session_state.abv_reale = 5.5

# --- 2. GESTIONE DATI (Magazzino, Shopping List e Database Ingredienti) ---

@st.cache_data
def carica_db(tipo):
    """Carica i database tecnici (Malti, Luppoli, ecc.) dai file JSON"""
    files = {
        "malti": "database_malti.json",
        "luppoli": "database_luppoli.json",
        "lieviti": "database_lieviti.json",
        "stili": "database_stili.json",
        "volumi": "database_volumi.json"
    }
    f_path = files.get(tipo)
    if f_path and os.path.exists(f_path):
        with open(f_path, "r", encoding='utf-8') as f:
            return json.load(f)
    return {}

def salva_db(tipo, dati):
    """Salva le modifiche ai database e pulisce la cache di Streamlit"""
    files = {
        "malti": "database_malti.json", 
        "luppoli": "database_luppoli.json", 
        "lieviti": "database_lieviti.json", 
        "stili": "database_stili.json", 
        "volumi": "database_volumi.json"
    }
    f_path = files.get(tipo)
    if f_path:
        with open(f_path, "w", encoding='utf-8') as f:
            json.dump(dati, f, indent=4, ensure_ascii=False)
        st.cache_data.clear() # Forza l'app a rileggere i dati aggiornati

def carica_magazzino():
    if os.path.exists("magazzino.json"):
        with open("magazzino.json", "r", encoding='utf-8') as f: 
            return json.load(f)
    return {"Fermentabili": {}, "Luppoli": {}, "Lieviti": {}, "shopping_list": {}}

def salva_magazzino(data):
    with open("magazzino.json", "w", encoding='utf-8') as f: 
        json.dump(data, f, indent=4)

def carica_archivio():
    if os.path.exists("archivio_ricette.json"):
        with open("archivio_ricette.json", "r", encoding='utf-8') as f: 
            return json.load(f)
    return {}

def salva_archivio(dati):
    with open("archivio_ricette.json", "w", encoding='utf-8') as f: 
        json.dump(dati, f, indent=4)

def genera_contesto_aigor(mag, archivio_json):
    """Trasforma i dati del JSON in testo per l'IA"""
    carrello = mag.get("shopping_list", {})
    malti_c = ", ".join([f"{n} ({q}kg)" for n, q in carrello.get("Fermentabili", {}).items()])
    luppoli_c = ", ".join([f"{n} ({q}g)" for n, q in carrello.get("Luppoli", {}).items()])
    
    ultime_ricette = "Nessuna"
    if archivio_json:
        nomi = list(archivio_json.keys())[-5:]
        ultime_ricette = ", ".join(nomi)
    
    contesto = f"""
    CONTESTO ATTUALE DI LUCA:
    - NEL CARRELLO: Malti: [{malti_c}], Luppoli: [{luppoli_c}].
    - ULTIME RICETTE PRODOTTE: {ultime_ricette}.
    - REGOLE: Luppolo pacchetti 30g/100g/250g. Malti sacchi 1kg/5kg/25kg.
    """
    return contesto

def aggiorna_scorta(categoria, nome, qta, prezzo=None, operazione="set"):
    mag = carica_magazzino()
    if nome not in mag[categoria]:
        mag[categoria][nome] = {"qta": 0.0, "prezzo": 0.0}
    attuale_qta = mag[categoria][nome].get("qta", 0.0)
    if operazione == "add":
        mag[categoria][nome]["qta"] = attuale_qta + qta
    elif operazione == "sub":
        mag[categoria][nome]["qta"] = max(0.0, attuale_qta - qta)
    else:
        mag[categoria][nome]["qta"] = qta
    if prezzo is not None:
        mag[categoria][nome]["prezzo"] = prezzo
    salva_magazzino(mag)

def aggiungi_a_shopping_list(ingredienti_ricetta):
    mag = carica_magazzino()
    if "shopping_list" not in mag or not isinstance(mag["shopping_list"].get("Fermentabili"), dict):
        mag["shopping_list"] = {"Fermentabili": {}, "Luppoli": {}, "Lieviti": {}}
    
    for ing in ingredienti_ricetta:
        nome = ing['nome']
        qta_necessaria = ing.get('kg') or ing.get('grammi') or 1
        cat = "Fermentabili" if 'kg' in ing else ("Luppoli" if 'grammi' in ing else "Lieviti")
        attuale = mag["shopping_list"][cat].get(nome, 0.0)
        mag["shopping_list"][cat][nome] = attuale + qta_necessaria
                
    salva_magazzino(mag)

# --- 3. CONFIGURAZIONE E STILE CSS ---
st.set_page_config(page_title="Sons of Brewery Master V7.1.5", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #1e2129; } 
    [data-testid="stSidebar"] { background-color: #0b0d10 !important; border-right: 2px solid #FFD700; }
    [data-testid="stWidgetLabel"] p { color: #FFD700 !important; font-weight: bold !important; background-color: transparent !important; }
    .stTextInput input, .stNumberInput input, div[data-baseweb="select"] > div { background-color: #ffffff !important; color: #000000 !important; }
    
    /* SELETTORE BOTTONI GIALLI - FORZA TESTO NERO */
    div.stButton > button, div.stButton > button p {
        background-color: #FFD700 !important;
        color: #000000 !important;
        font-weight: 900 !important; /* Extra bold per massima leggibilità */
    }

    /* FIX SPECIFICO PER I BOTTONI STANDARD */
    div.stButton > button {
        border-radius: 5px !important;
        border: 1px solid #000000 !important;
    }

    /* SELETTORE BOTTONI DOWNLOAD - TESTO BIANCO */
    div.stDownloadButton > button, div.stDownloadButton > button p {
        background-color: #4A90E2 !important;
        color: #ffffff !important;
        font-weight: bold !important;
        border-radius: 5px !important;
    }

    .stMarkdown, p, h4 { color: #ffffff !important; }
    h1, h2, h3 { color: #FFD700 !important; text-transform: uppercase; }
    .calc-box { background-color: #FFD700; padding: 20px; border-radius: 12px; color: #000000 !important; margin-bottom: 25px; }
    .calc-box-alert { background-color: #ff4b4b; padding: 15px; border-radius: 10px; color: white !important; margin-bottom: 10px; border: 1px solid white; }
    .ingrediente-box { background-color: #2d313d; padding: 12px; border-radius: 8px; border-left: 5px solid #FFD700; margin-bottom: 10px; }
    .metric-label { font-size: 0.9em; font-weight: bold; text-transform: uppercase; color: #000000 !important; }
    .metric-value { font-size: 1.5em; font-weight: 900; color: #000000 !important; }
    .color-swatch { width: 100%; height: 30px; border-radius: 5px; border: 2px solid #ffffff; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 4. FUNZIONI LOGICHE ---

def inizializza_database():
    """Trasforma i file JSON in DataFrame all'avvio dell'app"""
    def to_df(data, key_name):
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data, orient='index')
        df.index.name = key_name
        return df.reset_index()

    df_f = to_df(carica_db("malti"), "Fermentabile")
    df_l = to_df(carica_db("luppoli"), "Luppolo")
    df_y = to_df(carica_db("lieviti"), "Lievito")
    df_s = to_df(carica_db("stili"), "Stile")
    return df_f, df_l, df_y, df_s

# Creazione dei DataFrame globali
df_f_m, df_l_m, df_y_m, df_s_m = inizializza_database()

def salva_su_file(nome, stile, data_imb, litri, fermentabili, luppoli, yeast, mash_steps, og_r, fg_r, abv_r):
    """Salva la ricetta nell'archivio JSON"""
    archivio = carica_archivio()
    archivio[nome] = {
        "stile": stile, 
        "data_imbottigliamento": str(data_imb),
        "litri": litri, 
        "data": str(date.today()), 
        "fermentabili": fermentabili, 
        "luppoli": luppoli, 
        "yeast": yeast, 
        "mash_steps": mash_steps,
        "og_reale": og_r,
        "fg_reale": fg_r,
        "abv_reale": abv_r
    }
    salva_archivio(archivio)

def elimina_da_file(nome):
    """Elimina una ricetta dall'archivio"""
    archivio = carica_archivio()
    if nome in archivio:
        del archivio[nome]
        salva_archivio(archivio)

def calcola_ricetta_completa(litri_target, fermentabili, luppoli, lievito):
    """Logica di calcolo dei parametri della birra (OG, FG, IBU, EBC)"""
    EFF = 0.777; EVAP = 3.0; P_RAFF = 3.0; SM_MASH = 6.8; ASS_G = 0.96; R_MASH = 3.0
    og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc = 1.0, 0, 0, 0, 0, 0.0, 1.0, 0.0, 0.0
    
    if not fermentabili or litri_target <= 0: 
        return og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc
        
    tot_kg = sum(item['kg'] for item in fermentabili)
    punti_potenziali = sum(item['kg'] * item['ppg'] * 8.345 for item in fermentabili)
    og = 1 + ((punti_potenziali * EFF) / litri_target / 1000)
    
    galloni = litri_target * 0.264172
    mcu = sum(((item['kg'] * 2.20462) * (item.get('ebc', 0) / 1.97)) / galloni for item in fermentabili)
    if mcu > 0: 
        tot_ebc = (1.4922 * (mcu ** 0.6859)) * 1.97
        
    if lievito:
        att = lievito['attenuazione'] / 100 if lievito['attenuazione'] > 1 else lievito['attenuazione']
        fg = 1 + ((og - 1) * (1 - att))
        abv = (og - fg) * 131.25
        
    v_pre = litri_target + 2.0 + P_RAFF + EVAP
    a_m = (tot_kg * R_MASH) + SM_MASH
    a_s = (v_pre + (tot_kg * ASS_G)) - a_m
    
    boil_gravity = (og - 1) * (litri_target / v_pre) if v_pre > 0 else 0
    f_gravity = 1.65 * (0.000125 ** boil_gravity)
    
    for l in luppoli:
        if l['tipo'] == "Boil":
            util = f_gravity * ((1 - math.exp(-0.04 * l['valore_tempo'])) / 4.15)
            tot_ibu += ((l['grammi'] * (l['aa'] / 100) * 1000) * util) / litri_target
        elif l['tipo'] == "Hopstand":
            util = f_gravity * 0.03
            tot_ibu += ((l['grammi'] * (l['aa'] / 100) * 1000) * util) / litri_target
            
    return og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc

def ebc_to_hex(ebc):
    """Converte il valore EBC nel colore HEX corrispondente"""
    if ebc <= 4: return "#F3F9BE"
    elif ebc <= 8: return "#F6F510"
    elif ebc <= 16: return "#E0D01B"
    elif ebc <= 26: return "#CDAA37"
    elif ebc <= 39: return "#BE8C3A"
    elif ebc <= 59: return "#C17135"
    elif ebc <= 100: return "#462215"
    return "#080707"

def check_range(valore, v_min, v_max):
    """Confronto tra valore calcolato e range BJCP"""
    try:
        v_min, v_max = float(v_min), float(v_max)
        if v_min == 0 and v_max == 0: return "⚪", "gray", "n.d."
        if valore < v_min: return "⚠️", "#ff4b4b", f"Basso (min {v_min})"
        elif valore > v_max: return "⚠️", "#ff4b4b", f"Alto (max {v_max})"
        else: return "✅", "#28a745", "In stile"
    except: return "⚪", "gray", "errore dati"

def calcola_ripartizione_bottiglie(litri_netti):
    vol_075 = 9 * 0.75
    residuo = litri_netti - vol_075
    bot_066, bot_050 = 0, 0
    if residuo > 0:
        coppie = int(residuo // 3.48)
        bot_066, bot_050 = coppie * 3, coppie * 3
        residuo -= (coppie * 3.48)
        if residuo >= 1.98: bot_066 += 3; residuo -= 1.98
        elif residuo >= 1.50: bot_050 += 3; residuo -= 1.50
    return 9, bot_066, bot_050, max(0.0, residuo)

def ottimizza_pacchetti_malto(kg_necessari):
    if kg_necessari <= 0: return {}
    n25 = int(kg_necessari // 25); resto = kg_necessari % 25
    n5 = int(resto // 5); resto = resto % 5
    n1 = int(math.ceil(resto))
    res = {}
    if n25 > 0: res["Sacco 25kg"] = n25
    if n5 > 0: res["Sacco 5kg"] = n5
    if n1 > 0: res["Sacco 1kg"] = n1
    return res

def ottimizza_pacchetti_luppolo(g_necessari):
    if g_necessari <= 0: return {}
    n250 = int(g_necessari // 250); resto = g_necessari % 250
    if resto > 180: n250 += 1; resto = 0
    n100 = int(resto // 100); resto = resto % 100
    if resto > 70: n100 += 1; resto = 0
    n30 = int(math.ceil(resto / 30))
    res = {}
    if n250 > 0: res["Busta 250g"] = n250
    if n100 > 0: res["Busta 100g"] = n100
    if n30 > 0: res["Busta 30g"] = n30
    return res

def scala_ingredienti(nuovi_litri, vecchi_litri, fermentabili, luppoli):
    """Riscala le quantità in base ai nuovi litri target"""
    if vecchi_litri <= 0 or nuovi_litri == vecchi_litri:
        return fermentabili, luppoli
    ratio = nuovi_litri / vecchi_litri
    for f in fermentabili: f['kg'] = round(f['kg'] * ratio, 2)
    for l in luppoli: l['grammi'] = round(l['grammi'] * ratio, 1)
    return fermentabili, luppoli

# --- 5. FUNZIONE PDF SCHEDA ---
def genera_pdf_ricetta(nome, stile, litri, og, fg, abv, ibu, ebc, a_m, a_s, fermentabili, luppoli, lievito, mash_steps):
    pdf = FPDF()
    pdf.add_page()
    
    # --- REGISTRAZIONE FONT ---
    try:
        pdf.add_font('Freakshow', '', 'Carnevalee_Freakshow.ttf', uni=True)
        font_titolo = 'Freakshow'
    except:
        font_titolo = 'Helvetica'

    def clean(t):
        if not isinstance(t, str): t = str(t)
        return t.replace("’", "'").replace("“", '"').replace("”", '"').encode('latin-1', 'replace').decode('latin-1')

    # --- INTESTAZIONE NERO SU BIANCO ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_titolo, '', 45) 
    pdf.cell(0, 25, clean(nome.upper()), ln=True, align='C')
    
    # 2. STILE (Sempre nel tuo font, un po' più piccolo)
    pdf.set_font(font_titolo, '', 25) 
    testo_stile = f"Stile: {stile}" if stile else "Stile: Libero"
    pdf.cell(0, 15, clean(testo_stile), ln=True, align='C')
    
    # Linea di separazione elegante
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(10)

    # --- RIEPILOGO TECNICO ---
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 8, " PARAMETRI TECNICI", ln=True, fill=True)
    
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(38, 10, clean(f" OG: {og:.3f}"), border='LTB')
    pdf.cell(38, 10, clean(f" FG: {fg:.3f}"), border='TB')
    pdf.cell(38, 10, clean(f" ABV: {abv:.1f}%"), border='TB')
    pdf.cell(38, 10, clean(f" IBU: {ibu:.1f}"), border='TB')
    pdf.cell(38, 10, clean(f" EBC: {ebc:.1f}"), border='RTB', ln=True)
    pdf.ln(5)

    # Volumi Acqua
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 8, " VOLUMI ACQUA", ln=True, fill=True)
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(63, 10, clean(f" Mash: {a_m:.1f} L"), border=1)
    pdf.cell(63, 10, clean(f" Sparge: {a_s:.1f} L"), border=1)
    pdf.cell(64, 10, clean(f" Totale: {litri} L"), border=1, ln=True)
    pdf.ln(5)

    # Sezioni Ingredienti
    def sez(t, d, r, g, b):
        pdf.set_fill_color(r, g, b)
        pdf.set_font("Helvetica", 'B', 11)
        pdf.cell(0, 8, f" {t}", ln=True, fill=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", '', 10)
        if d:
            for item in d:
                pdf.cell(0, 7, clean(f"  > {item}"), ln=True)
        else:
            pdf.cell(0, 7, "  - Nessun dato", ln=True)
        pdf.ln(3)

    sez("MALTI E FERMENTABILI", [f"{f['nome']}: {f['kg']} kg" for f in fermentabili], 255, 245, 200)
    sez("LUPPOLI", [f"{l['tipo']}: {l['nome']} {l['grammi']}g ({l['valore_tempo']} min/gg)" for l in luppoli], 220, 240, 220)
    sez("LIEVITO", [f"{lievito['nome']}" if lievito else "Nessuno"], 240, 240, 240)
    sez("MASH", [f"{s['temp']} C per {s['tempo']} min" for s in mash_steps], 210, 230, 250)

    return bytes(pdf.output())

# --- 5b. NUOVA FUNZIONE PDF ETICHETTE (MODIFICATA) ---
def genera_pdf_etichette(nome, stile, abv, data_imb):
    from fpdf import FPDF
    import os

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    if os.path.exists("Carnevalee_Freakshow.ttf"):
        pdf.add_font("Carnivalee", "", "Carnevalee_Freakshow.ttf")
        font_main = "Carnivalee"
    else:
        font_main = "Helvetica"
    
    # Parametri di scala
    BASE_W, BASE_H = 62, 85
    w_et, h_et = 55, 73   # Dimensioni attuali
    scale = min(w_et / BASE_W, h_et / BASE_H)

    def s(v):
        return v * scale

    # Margini centrati
    m_x = (210 - (3 * w_et)) / 2
    m_y = (297 - (3 * h_et)) / 2

    for i in range(9):
        col = i % 3
        row = i // 3
        x = m_x + (col * w_et)
        y = m_y + (row * h_et)

        # Bordo etichetta
        pdf.set_line_width(1.4)
        pdf.rect(x, y, w_et, h_et)
        pdf.set_line_width(0.2)

        # 1. Logo Upper
        if os.path.exists("Logo Upper.png"):
            pdf.image("Logo Upper.png", x + s(4), y + s(3), w_et - s(8))

        # 2. Logo Medium (AUMENTATA DIMENSIONE p_w)
        if os.path.exists("Logo Medium.png"):
            p_w = s(35) # <--- Aumentato da 28 a 35
            pdf.image("Logo Medium.png", x + (w_et - p_w) / 2, y + s(14), p_w)

        # 3. EST 2021 (Commentato come da tua richiesta)
        pdf.set_font("Times", 'B', max(1, int(7 * scale)))
        pdf.set_xy(x, y + s(48))
        # pdf.cell(w_et, s(5), "EST. 2021", align='C')

        # 4. Nome birra (RIGA TITOLO - INGRANDITA)
        pdf.set_font(font_main, "", max(1, int(20 * scale))) # <--- Aumentato da 16 a 20
        pdf.set_xy(x, y + s(55)) # <--- Alzata la Y da 53 a 48 per dare spazio
        pdf.cell(w_et, s(10), nome.upper(), align='C')

        # --- 4. STILE (Allineato a sinistra) ---
        pdf.set_font(font_main, "", max(1, int(14 * scale)))
        # Usiamo x + 2 per distanziarlo leggermente dal bordo nero
        pdf.set_xy(x + 2, y + s(75)) 
        pdf.cell(s(30), s(10), stile.upper(), align='L')

        # --- 5. ABV (Allineato a destra) ---
        # Usiamo un font più grande come richiesto
        pdf.set_font(font_main, "", max(1, int(18 * scale)))
        # Posizioniamo la cella in modo che finisca a 2mm dal bordo destro
        pdf.set_xy(x + w_et - s(15) - 2, y + s(75))
        pdf.cell(s(15), s(10), f"{abv:.1f}%", align='R')


        # 6. Icona Pregnant (SPOSTATA PIU' IN ALTO)
        if os.path.exists("Pregnant.png"):
            pdf.image("Pregnant.png", x + s(2.5), y + s(64.5), s(6)) # <--- Spostato da 77.5 a 64.5

        # 7. Data imbottigliamento (AUMENTATO FONT E CENTRATA)
        pdf.set_font("Times", "", max(1, int(7 * scale))) # <--- Aumentato da 5.5 a 7
        with pdf.rotation(90, x + w_et - s(1.5), y + s(55)): # <--- Rotazione centrata a 36mm
            pdf.text(x + w_et - s(1.5), y + s(55), f"Imbottigliata il {data_imb}")

    return bytes(pdf.output())

# --- 6. SIDEBAR ---
# Recuperiamo gli stili dal nuovo database JSON invece che dall'Excel
db_stili_sidebar = carica_db("stili")
opzioni_s = sorted(list(db_stili_sidebar.keys()))

with st.sidebar:
    if os.path.exists("Logo.png"): 
        st.image("Logo.png", use_container_width=True)
    
    st.markdown("<h2 style='color:#FFD700;'>SONS OF BREWERY</h2>", unsafe_allow_html=True)
    
    # PULSANTI DI NAVIGAZIONE
    if st.button("🏠 DASHBOARD", width="stretch"): 
        st.session_state.pagina = "Home"; st.rerun()
    if st.button("🛠️ EDITOR RICETTA", width="stretch"): 
        st.session_state.pagina = "Editor"; st.rerun()
    if st.button("📦 MAGAZZINO", width="stretch"): 
        st.session_state.pagina = "Magazzino"; st.rerun()
    if st.button("🤖 AIGOR", width="stretch"): 
        st.session_state.pagina = "AIGOR"; st.rerun()
    
    # NUOVO PULSANTE DATABASE
    if st.button("⚙️ DATABASE", width="stretch"): 
        st.session_state.pagina = "Database"; st.rerun()

    st.divider()
    st.subheader("📁 ARCHIVIO")
    archivio = carica_archivio()
    for nome_r in list(archivio.keys()):
        c_side = st.columns([0.8, 0.2])
        if c_side[0].button(f"📖 {nome_r}", key=f"s_{nome_r}", width="stretch"):
            d = archivio[nome_r]
            st.session_state.nome_b, st.session_state.stile_b = nome_r, d.get('stile','')
            if 'data_imbottigliamento' in d:
                st.session_state.data_imb = date.fromisoformat(d['data_imbottigliamento'])
            st.session_state.litri_f = d.get('litri',25.0)
            st.session_state.f_list = d.get('fermentabili',[])
            st.session_state.l_list = d.get('luppoli',[])
            st.session_state.m_list = d.get('mash_steps',[])
            st.session_state.yeast_sel = d.get('yeast')
            st.session_state.pagina = "Editor"; st.rerun()
        
        if c_side[1].button("🗑️", key=f"d_{nome_r}"): 
            elimina_da_file(nome_r); st.rerun()

# --- 7. PAGINA MAGAZZINO ---
if st.session_state.pagina == "Magazzino":
    st.title("📦 Magazzino Scorte")
    mag = carica_magazzino()
    t1, t2, t3 = st.tabs(["Malti", "Luppoli", "Lieviti"])
    
    with t1:
        c1, c2, c3, c4 = st.columns([3,1,1,1])
        # Usiamo i nomi dai database caricati dai JSON
        lista_malti = sorted(df_f_m["Fermentabile"].tolist()) if not df_f_m.empty else []
        m_sel = c1.selectbox("Malto", options=[""] + lista_malti)
        m_qta = c2.number_input("Kg", min_value=0.0, step=0.5, key="add_m_qta")
        m_prz = c3.number_input("Euro", min_value=0.0, step=0.5, key="add_m_prz")
        if c4.button("CARICA", key="btn_m"):
            if m_sel:
                aggiorna_scorta("Fermentabili", m_sel, m_qta, m_prz, "add")
                st.rerun()
            else:
                st.error("Seleziona un malto")

        for k, v in mag["Fermentabili"].items():
            cc = st.columns([3,1,1,1])
            cc[0].write(f"**{k}**")
            cc[1].write(f"{v['qta']:.1f} Kg")
            cc[2].write(f"{v.get('prezzo', 0.0):.2f} €")
            if cc[3].button("🗑️", key=f"del_f_{k}"):
                del mag["Fermentabili"][k]
                salva_magazzino(mag)
                st.rerun()

    with t2:
        c1, c2, c3, c4 = st.columns([3,1,1,1])
        lista_luppoli = sorted(df_l_m["Luppolo"].tolist()) if not df_l_m.empty else []
        l_sel = c1.selectbox("Luppolo", options=[""] + lista_luppoli)
        l_qta = c2.number_input("Grammi", min_value=0.0, step=10.0, key="add_l_qta")
        l_prz = c3.number_input("Euro", min_value=0.0, step=0.5, key="add_l_prz")
        if c4.button("CARICA", key="btn_l"):
            if l_sel:
                aggiorna_scorta("Luppoli", l_sel, l_qta, l_prz, "add")
                st.rerun()
            else:
                st.error("Seleziona un luppolo")

        for k, v in mag["Luppoli"].items():
            cc = st.columns([3,1,1,1])
            cc[0].write(f"**{k}**")
            cc[1].write(f"{v['qta']:.0f} g")
            cc[2].write(f"{v.get('prezzo', 0.0):.2f} €")
            if cc[3].button("🗑️", key=f"del_l_{k}"):
                del mag["Luppoli"][k]
                salva_magazzino(mag)
                st.rerun()

    with t3:
        c1, c2, c3, c4 = st.columns([3,1,1,1])
        lista_lieviti = sorted(df_y_m["Lievito"].tolist()) if not df_y_m.empty else []
        y_sel = c1.selectbox("Lievito", options=[""] + lista_lieviti)
        y_qta = c2.number_input("Unità", min_value=0.0, step=1.0, key="add_y_qta")
        y_prz = c3.number_input("Euro", min_value=0.0, step=0.5, key="add_y_prz")
        if c4.button("CARICA", key="btn_y"):
            if y_sel:
                aggiorna_scorta("Lieviti", y_sel, y_qta, y_prz, "add")
                st.rerun()
            else:
                st.error("Seleziona un lievito")

        for k, v in mag["Lieviti"].items():
            cc = st.columns([3,1,1,1])
            cc[0].write(f"**{k}**")
            cc[1].write(f"{v['qta']:.0f} Unità")
            cc[2].write(f"{v.get('prezzo', 0.0):.2f} €")
            if cc[3].button("🗑️", key=f"del_y_{k}"):
                del mag["Lieviti"][k]
                salva_magazzino(mag)
                st.rerun()

    st.divider()
    st.header("🛒 CARRELLO: COSA DEVI COMPRARE")
    st.caption("Suggerimenti ottimizzati in base ai formati commerciali (Sacchi e Pacchetti).")

    carrello_lordo = mag.get("shopping_list", {"Fermentabili": {}, "Luppoli": {}, "Lieviti": {}})
    tab_c1, tab_c2, tab_c3 = st.tabs(["🌾 MALTI", "🌿 LUPPOLI", "🧫 LIEVITI"])
    
    with tab_c1:
        malti_da_comprare = False
        for nome, qta_lorda in carrello_lordo.get("Fermentabili", {}).items():
            qta_magazzino = mag["Fermentabili"].get(nome, {}).get("qta", 0.0)
            da_comprare = max(0.0, qta_lorda - qta_magazzino)
            if da_comprare > 0:
                s25 = int(da_comprare // 25); rest = da_comprare % 25
                s5 = int(rest // 5); rest = rest % 5
                s1 = math.ceil(rest)
                suggerimento = []
                if s25 > 0: suggerimento.append(f"{s25}x25kg")
                if s5 > 0: suggerimento.append(f"{s5}x5kg")
                if s1 > 0: suggerimento.append(f"{s1}x1kg")
                st.write(f"🔸 **{nome}**: {da_comprare:.2f} kg  \n&nbsp;&nbsp;&nbsp;&nbsp;📦 *Suggerimento: {' + '.join(suggerimento)}*")
                malti_da_comprare = True
        if not malti_da_comprare: st.info("Nessun malto da acquistare.")
        if st.button("🗑️ SVUOTA MALTI", key="clear_c_f", use_container_width=True):
            mag["shopping_list"]["Fermentabili"] = {}; salva_magazzino(mag); st.rerun()

    with tab_c2:
        luppoli_da_comprare = False
        for nome, qta_lorda in carrello_lordo.get("Luppoli", {}).items():
            qta_magazzino = mag["Luppoli"].get(nome, {}).get("qta", 0.0)
            da_comprare = max(0.0, qta_lorda - qta_magazzino)
            if da_comprare > 0:
                p250 = int(da_comprare // 250); rest = da_comprare % 250
                p100 = int(rest // 100); rest = rest % 100
                p30 = math.ceil(rest / 30)
                suggerimento = []
                if p250 > 0: suggerimento.append(f"{p250}x250g")
                if p100 > 0: suggerimento.append(f"{p100}x100g")
                if p30 > 0: suggerimento.append(f"{p30}x30g")
                st.write(f"🔸 **{nome}**: {da_comprare:.0f} g  \n&nbsp;&nbsp;&nbsp;&nbsp;📦 *Suggerimento: {' + '.join(suggerimento)}*")
                luppoli_da_comprare = True
        if not luppoli_da_comprare: st.info("Nessun luppolo da acquistare.")
        if st.button("🗑️ SVUOTA LUPPOLI", key="clear_c_l", use_container_width=True):
            mag["shopping_list"]["Luppoli"] = {}; salva_magazzino(mag); st.rerun()

    with tab_c3:
        lieviti_da_comprare = False
        for nome, qta_lorda in carrello_lordo.get("Lieviti", {}).items():
            qta_magazzino = mag["Lieviti"].get(nome, {}).get("qta", 0.0)
            da_comprare = max(0.0, qta_lorda - qta_magazzino)
            if da_comprare > 0:
                st.write(f"🔸 **{nome}**: {int(da_comprare)} bustine")
                lieviti_da_comprare = True
        if not lieviti_da_comprare: st.info("Nessun lievito da acquistare.")
        if st.button("🗑️ SVUOTA LIEVITI", key="clear_c_y", use_container_width=True):
            mag["shopping_list"]["Lieviti"] = {}; salva_magazzino(mag); st.rerun()

# --- 8. PAGINA EDITOR ---
elif st.session_state.pagina == "Editor":
    st.title(f"🛠️ Editor: {st.session_state.nome_b}")
    mag = carica_magazzino()
    
    # --- 1. INPUT DATI PRINCIPALI ---
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    st.session_state.nome_b = c1.text_input("NOME", value=st.session_state.nome_b)
    st.session_state.stile_b = c2.selectbox("STILE", options=[""] + opzioni_s, index=(opzioni_s.index(st.session_state.stile_b)+1 if st.session_state.stile_b in opzioni_s else 0))
    
    nuovi_litri = c3.number_input("LITRI", value=float(st.session_state.litri_f), step=1.0)
    st.session_state.data_imb = c4.date_input("DATA IMB.", value=st.session_state.data_imb)

    # Logica di Scaling
    if nuovi_litri != st.session_state.litri_f:
        if st.session_state.f_list or st.session_state.l_list:
            st.warning(f"⚠️ Hai cambiato il volume da {st.session_state.litri_f}L a {nuovi_litri}L.")
            if st.button("🔄 SCALA INGREDIENTI ORA", use_container_width=True):
                f_scalati, l_scalati = scala_ingredienti(nuovi_litri, st.session_state.litri_f, st.session_state.f_list, st.session_state.l_list)
                st.session_state.f_list, st.session_state.l_list = f_scalati, l_scalati
                st.session_state.litri_f = nuovi_litri 
                st.rerun()
        else:
            st.session_state.litri_f = nuovi_litri

    # Calcolo parametri tecnici
    og, v_pre, a_m, a_s, kg_t, ibu, fg, abv, ebc = calcola_ricetta_completa(st.session_state.litri_f, st.session_state.f_list, st.session_state.l_list, st.session_state.yeast_sel)
    
    # --- RECUPERO LIMITI BJCP ---
    bjcp_limits = {"og": (0,0), "fg": (0,0), "ibu": (0,0), "ebc": (0,0), "abv": (0,0)}
    vol_default = 2.3
    
    if st.session_state.stile_b and not df_s_m.empty:
        s_info = df_s_m[df_s_m["Stile"] == st.session_state.stile_b].iloc[0]
        
        def to_std(v):
            val = float(v)
            if val > 1000: return val / 1000
            if val > 1: return 1 + (val / 1000)
            return val

        bjcp_limits = {
            "og": (to_std(s_info.get('OG_min', 0)), to_std(s_info.get('OG_max', 0))),
            "fg": (to_std(s_info.get('FG_min', 0)), to_std(s_info.get('FG_max', 0))),
            "ibu": (float(s_info.get('IBU_min', 0)), float(s_info.get('IBU_max', 0))),
            "ebc": (float(s_info.get('EBC_min', 0)), float(s_info.get('EBC_max', 0))),
            "abv": (float(s_info.get('ABV_min', 0)), float(s_info.get('ABV_max', 0))),
        }
        vol_default = float(s_info.get('Vol_CO2', s_info.get('Volumi', 2.3)))
    
    # --- 2. RECUPERO VOLUMI CO2 ---
    if st.session_state.stile_b and not df_s_m.empty:
        s_info = df_s_m[df_s_m["Stile"] == st.session_state.stile_b]
        if not s_info.empty:
            colonne = s_info.columns
            colonna_target = "Vol_CO2" if "Vol_CO2" in colonne else ("Volumi" if "Volumi" in colonne else None)
            
            if colonna_target:
                try:
                    val = float(s_info[colonna_target].values[0])
                    vol_default = val if val > 0 else 2.3
                except:
                    vol_default = 2.3

    # --- 3. CALCOLO COSTI ---
    costo_tot = 0.0
    for f in st.session_state.f_list:
        m_mag = mag["Fermentabili"].get(f['nome'], {})
        q_ref = m_mag.get('qta_iniziale', m_mag.get('qta', 1))
        costo_tot += (m_mag.get('prezzo', 0) / q_ref) * f['kg'] if q_ref > 0 else 0
        
    for l in st.session_state.l_list:
        l_mag = mag["Luppoli"].get(l['nome'], {})
        q_ref = l_mag.get('qta_iniziale', l_mag.get('qta', 1))
        costo_tot += (l_mag.get('prezzo', 0) / q_ref) * l['grammi'] if q_ref > 0 else 0
        
    if st.session_state.yeast_sel:
        y_mag = mag["Lieviti"].get(st.session_state.yeast_sel['nome'], {})
        costo_tot += y_mag.get('prezzo', 0)

    # --- 4. BOX TECNICO E TILE COSTI ---
    st.markdown(f"""<div class="calc-box"><div style="display:flex; justify-content:space-around; text-align:center;">
        <div><div class="metric-label">OG/FG</div><div class="metric-value">{og:.3f}/{fg:.3f}</div></div>
        <div><div class="metric-label">ABV%</div><div class="metric-value" style="color:#d40000;">{abv:.1f}%</div></div>
        <div><div class="metric-label">IBU/EBC</div><div class="metric-value">{ibu:.1f}/{ebc:.1f}</div><div class="color-swatch" style="background-color:{ebc_to_hex(ebc)};"></div></div>
        <div><div class="metric-label">MASH/SPARGE</div><div class="metric-value">{a_m:.1f}/{a_s:.1f}L</div></div>
    </div></div>""", unsafe_allow_html=True)

    # --- DASHBOARD BJCP ---
    st.markdown("### 📊 Rispetto dello Stile (BJCP)")
    with st.container(border=True):
        bj1, bj2, bj3, bj4, bj5 = st.columns(5)
        controlli = [
            (bj1, "OG", og, bjcp_limits["og"], "{:.3f}"),
            (bj2, "FG", fg, bjcp_limits["fg"], "{:.3f}"),
            (bj3, "ABV", abv, bjcp_limits["abv"], "{:.1f}%"),
            (bj4, "IBU", ibu, bjcp_limits["ibu"], "{:.0f}"),
            (bj5, "EBC", ebc, bjcp_limits["ebc"], "{:.0f}")
        ]
        for col, nome, val, lim, fmt in controlli:
            icona, colore, nota = check_range(val, lim[0], lim[1])
            with col:
                st.markdown(f"**{nome}**")
                st.markdown(f"<p style='color:{colore}; font-size:18px; font-weight:bold; margin:0;'>{icona} {fmt.format(val)}</p>", unsafe_allow_html=True)
                st.caption(f"Lim: {lim[0]}-{lim[1]}")

    # --- RILEVAZIONI EFFETTIVE ---
    st.markdown("### 📏 RILEVAZIONI EFFETTIVE")
    with st.container(border=True):
        cr1, cr2, cr3 = st.columns(3)
        st.session_state.og_reale = cr1.number_input("OG Rilevata", value=float(st.session_state.og_reale), format="%.3f", step=0.001)
        st.session_state.fg_reale = cr2.number_input("FG Rilevata", value=float(st.session_state.fg_reale), format="%.3f", step=0.001)
        abv_reale_calc = (st.session_state.og_reale - st.session_state.fg_reale) * 131.25 + 0.5
        st.session_state.abv_reale = cr3.number_input("ABV % Finale (+0.5%)", value=float(abv_reale_calc), format="%.1f")

    # TILE VERDE COSTI
    st.markdown(f"""<div class="calc-box" style="background-color: #28a745; color: white !important;"><div style="display:flex; justify-content:space-around; text-align:center;">
            <div><div class="metric-label" style="color:white !important;">Costo Totale Cotta</div><div class="metric-value" style="color:white !important;">{costo_tot:.2f} €</div></div>
            <div><div class="metric-label" style="color:white !important;">Costo al Litro</div><div class="metric-value" style="color:white !important;">{(costo_tot/st.session_state.litri_f if st.session_state.litri_f>0 else 0):.2f} €/L</div></div>
        </div></div>""", unsafe_allow_html=True)

    # --- 5. TABS INGREDIENTI ---
    t1, t2, t3, t4 = st.tabs(["🌾 FERMENTABILI", "🌿 LUPPOLI", "🧫 LIEVITO", "🌡️ MASH"])
    
    with t1:
        f1, f2 = st.columns([3, 1])
        s_f = f1.selectbox("MALTO", [""] + sorted(df_f_m["Fermentabile"].tolist()), key="sel_f_ed")
        k_f = f2.number_input("Kg", min_value=0.0, step=0.1, key="qta_f_ed")
        if st.button("➕ Aggiungi Malto") and s_f and k_f > 0:
            d = df_f_m[df_f_m["Fermentabile"] == s_f].iloc[0]
            st.session_state.f_list.append({'nome': s_f, 'kg': k_f, 'ppg': float(d['PPG']), 'Ecco il codice sorgente Python per la tua applicazione Streamlit aggiornato con l'integrazione del nuovo SDK ufficiale `google-genai` (in sostituzione del pacchetto legacy `google-generativeai`).

### Modifiche Principali Applicate:
1. **Importazione dell'SDK**: Utilizzo di `from google import genai` e `from google.genai import types`.
2. **Inizializzazione del Client**: Utilizzo di `client = genai.Client(api_key=...)` in luogo della vecchia chiamata globale `genai.configure()`.
3. **Chiamate di Generazione**: Migrazione a `client.models.generate_content(...)` specificando il modello `gemini-2.5-flash`.

```python
import streamlit as st
import pandas as pd
import os
import math
import json
from datetime import date
from fpdf import FPDF 
from google import genai
from google.genai import types

# --- CARICAMENTO API KEY GEMINI (MODALITÀ SICURA) ---
def get_api_key():
    # 1. Prova a leggere dai Secrets di Streamlit (per il Cloud)
    if "GOOGLE_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_API_KEY"]
    
    # 2. Backup per il locale: se hai ancora il file .txt lo legge, 
    # altrimenti cerca nelle variabili d'ambiente
    if os.path.exists("key_gemini.txt"):
        with open("key_gemini.txt", "r") as f:
            return f.read().strip()
            
    return os.environ.get("GOOGLE_API_KEY", None)

api_key = get_api_key()

if api_key:
    client = genai.Client(api_key=api_key)
    st.session_state["api_key_configured"] = True
else:
    client = None
    st.error("Chiave API non trovata! Configura i Secrets su Streamlit o il file key_gemini.txt in locale.")

# --- 1. INIZIALIZZAZIONE SESSION STATE ---
if 'pagina' not in st.session_state: st.session_state.pagina = "Home"
if 'chat_history' not in st.session_state: st.session_state.chat_history = [] # Memoria Agente AI
if 'nome_b' not in st.session_state: st.session_state.nome_b = "Nuova Ricetta"
if 'stile_b' not in st.session_state: st.session_state.stile_b = ""
if 'data_imb' not in st.session_state: st.session_state.data_imb = date.today()
if 'litri_f' not in st.session_state: st.session_state.litri_f = 25.0
if 'litri_precedenti' not in st.session_state: st.session_state.litri_precedenti = 25.0 # Per monitorare i cambi
if 'f_list' not in st.session_state: st.session_state.f_list = []
if 'l_list' not in st.session_state: st.session_state.l_list = []
if 'm_list' not in st.session_state: st.session_state.m_list = []
if 'yeast_sel' not in st.session_state: st.session_state.yeast_sel = None
if 'og_reale' not in st.session_state: st.session_state.og_reale = 1.050
if 'fg_reale' not in st.session_state: st.session_state.fg_reale = 1.010
if 'abv_reale' not in st.session_state: st.session_state.abv_reale = 5.5

# --- 2. GESTIONE DATI (Magazzino, Shopping List e Database Ingredienti) ---

@st.cache_data
def carica_db(tipo):
    """Carica i database tecnici (Malti, Luppoli, ecc.) dai file JSON"""
    files = {
        "malti": "database_malti.json",
        "luppoli": "database_luppoli.json",
        "lieviti": "database_lieviti.json",
        "stili": "database_stili.json",
        "volumi": "database_volumi.json"
    }
    f_path = files.get(tipo)
    if f_path and os.path.exists(f_path):
        with open(f_path, "r", encoding='utf-8') as f:
            return json.load(f)
    return {}

def salva_db(tipo, dati):
    """Salva le modifiche ai database e pulisce la cache di Streamlit"""
    files = {
        "malti": "database_malti.json", 
        "luppoli": "database_luppoli.json", 
        "lieviti": "database_lieviti.json", 
        "stili": "database_stili.json", 
        "volumi": "database_volumi.json"
    }
    f_path = files.get(tipo)
    if f_path:
        with open(f_path, "w", encoding='utf-8') as f:
            json.dump(dati, f, indent=4, ensure_ascii=False)
        st.cache_data.clear() # Forza l'app a rileggere i dati aggiornati

def carica_magazzino():
    if os.path.exists("magazzino.json"):
        with open("magazzino.json", "r", encoding='utf-8') as f: 
            return json.load(f)
    return {"Fermentabili": {}, "Luppoli": {}, "Lieviti": {}, "shopping_list": {}}

def salva_magazzino(data):
    with open("magazzino.json", "w", encoding='utf-8') as f: 
        json.dump(data, f, indent=4)

def carica_archivio():
    if os.path.exists("archivio_ricette.json"):
        with open("archivio_ricette.json", "r", encoding='utf-8') as f: 
            return json.load(f)
    return {}

def salva_archivio(dati):
    with open("archivio_ricette.json", "w", encoding='utf-8') as f: 
        json.dump(dati, f, indent=4)

def genera_contesto_aigor(mag, archivio_json):
    """Trasforma i dati del JSON in testo per l'IA"""
    carrello = mag.get("shopping_list", {})
    malti_c = ", ".join([f"{n} ({q}kg)" for n, q in carrello.get("Fermentabili", {}).items()])
    luppoli_c = ", ".join([f"{n} ({q}g)" for n, q in carrello.get("Luppoli", {}).items()])
    
    ultime_ricette = "Nessuna"
    if archivio_json:
        nomi = list(archivio_json.keys())[-5:]
        ultime_ricette = ", ".join(nomi)
    
    contesto = f"""
    CONTESTO ATTUALE DI LUCA:
    - NEL CARRELLO: Malti: [{malti_c}], Luppoli: [{luppoli_c}].
    - ULTIME RICETTE PRODOTTE: {ultime_ricette}.
    - REGOLE: Luppolo pacchetti 30g/100g/250g. Malti sacchi 1kg/5kg/25kg.
    """
    return contesto

def aggiorna_scorta(categoria, nome, qta, prezzo=None, operazione="set"):
    mag = carica_magazzino()
    if nome not in mag[categoria]:
        mag[categoria][nome] = {"qta": 0.0, "prezzo": 0.0}
    attuale_qta = mag[categoria][nome].get("qta", 0.0)
    if operazione == "add":
        mag[categoria][nome]["qta"] = attuale_qta + qta
    elif operazione == "sub":
        mag[categoria][nome]["qta"] = max(0.0, attuale_qta - qta)
    else:
        mag[categoria][nome]["qta"] = qta
    if prezzo is not None:
        mag[categoria][nome]["prezzo"] = prezzo
    salva_magazzino(mag)

def aggiungi_a_shopping_list(ingredienti_ricetta):
    mag = carica_magazzino()
    if "shopping_list" not in mag or not isinstance(mag["shopping_list"].get("Fermentabili"), dict):
        mag["shopping_list"] = {"Fermentabili": {}, "Luppoli": {}, "Lieviti": {}}
    
    for ing in ingredienti_ricetta:
        nome = ing['nome']
        qta_necessaria = ing.get('kg') or ing.get('grammi') or 1
        cat = "Fermentabili" if 'kg' in ing else ("Luppoli" if 'grammi' in ing else "Lieviti")
        attuale = mag["shopping_list"][cat].get(nome, 0.0)
        mag["shopping_list"][cat][nome] = attuale + qta_necessaria
                
    salva_magazzino(mag)

# --- 3. CONFIGURAZIONE E STILE CSS ---
st.set_page_config(page_title="Sons of Brewery Master V7.1.5", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #1e2129; } 
    [data-testid="stSidebar"] { background-color: #0b0d10 !important; border-right: 2px solid #FFD700; }
    [data-testid="stWidgetLabel"] p { color: #FFD700 !important; font-weight: bold !important; background-color: transparent !important; }
    .stTextInput input, .stNumberInput input, div[data-baseweb="select"] > div { background-color: #ffffff !important; color: #000000 !important; }
    
    /* SELETTORE BOTTONI GIALLI - FORZA TESTO NERO */
    div.stButton > button, div.stButton > button p {
        background-color: #FFD700 !important;
        color: #000000 !important;
        font-weight: 900 !important; /* Extra bold per massima leggibilità */
    }

    /* FIX SPECIFICO PER I BOTTONI STANDARD */
    div.stButton > button {
        border-radius: 5px !important;
        border: 1px solid #000000 !important;
    }

    /* SELETTORE BOTTONI DOWNLOAD - TESTO BIANCO */
    div.stDownloadButton > button, div.stDownloadButton > button p {
        background-color: #4A90E2 !important;
        color: #ffffff !important;
        font-weight: bold !important;
        border-radius: 5px !important;
    }

    .stMarkdown, p, h4 { color: #ffffff !important; }
    h1, h2, h3 { color: #FFD700 !important; text-transform: uppercase; }
    .calc-box { background-color: #FFD700; padding: 20px; border-radius: 12px; color: #000000 !important; margin-bottom: 25px; }
    .calc-box-alert { background-color: #ff4b4b; padding: 15px; border-radius: 10px; color: white !important; margin-bottom: 10px; border: 1px solid white; }
    .ingrediente-box { background-color: #2d313d; padding: 12px; border-radius: 8px; border-left: 5px solid #FFD700; margin-bottom: 10px; }
    .metric-label { font-size: 0.9em; font-weight: bold; text-transform: uppercase; color: #000000 !important; }
    .metric-value { font-size: 1.5em; font-weight: 900; color: #000000 !important; }
    .color-swatch { width: 100%; height: 30px; border-radius: 5px; border: 2px solid #ffffff; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 4. FUNZIONI LOGICHE ---

def inizializza_database():
    """Trasforma i file JSON in DataFrame all'avvio dell'app"""
    def to_df(data, key_name):
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data, orient='index')
        df.index.name = key_name
        return df.reset_index()

    df_f = to_df(carica_db("malti"), "Fermentabile")
    df_l = to_df(carica_db("luppoli"), "Luppolo")
    df_y = to_df(carica_db("lieviti"), "Lievito")
    df_s = to_df(carica_db("stili"), "Stile")
    return df_f, df_l, df_y, df_s

# Creazione dei DataFrame globali
df_f_m, df_l_m, df_y_m, df_s_m = inizializza_database()

def salva_su_file(nome, stile, data_imb, litri, fermentabili, luppoli, yeast, mash_steps, og_r, fg_r, abv_r):
    """Salva la ricetta nell'archivio JSON"""
    archivio = carica_archivio()
    archivio[nome] = {
        "stile": stile, 
        "data_imbottigliamento": str(data_imb),
        "litri": litri, 
        "data": str(date.today()), 
        "fermentabili": fermentabili, 
        "luppoli": luppoli, 
        "yeast": yeast, 
        "mash_steps": mash_steps,
        "og_reale": og_r,
        "fg_reale": fg_r,
        "abv_reale": abv_r
    }
    salva_archivio(archivio)

def elimina_da_file(nome):
    """Elimina una ricetta dall'archivio"""
    archivio = carica_archivio()
    if nome in archivio:
        del archivio[nome]
        salva_archivio(archivio)

def calcola_ricetta_completa(litri_target, fermentabili, luppoli, lievito):
    """Logica di calcolo dei parametri della birra (OG, FG, IBU, EBC)"""
    EFF = 0.777; EVAP = 3.0; P_RAFF = 3.0; SM_MASH = 6.8; ASS_G = 0.96; R_MASH = 3.0
    og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc = 1.0, 0, 0, 0, 0, 0.0, 1.0, 0.0, 0.0
    
    if not fermentabili or litri_target <= 0: 
        return og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc
        
    tot_kg = sum(item['kg'] for item in fermentabili)
    punti_potenziali = sum(item['kg'] * item['ppg'] * 8.345 for item in fermentabili)
    og = 1 + ((punti_potenziali * EFF) / litri_target / 1000)
    
    galloni = litri_target * 0.264172
    mcu = sum(((item['kg'] * 2.20462) * (item.get('ebc', 0) / 1.97)) / galloni for item in fermentabili)
    if mcu > 0: 
        tot_ebc = (1.4922 * (mcu ** 0.6859)) * 1.97
        
    if lievito:
        att = lievito['attenuazione'] / 100 if lievito['attenuazione'] > 1 else lievito['attenuazione']
        fg = 1 + ((og - 1) * (1 - att))
        abv = (og - fg) * 131.25
        
    v_pre = litri_target + 2.0 + P_RAFF + EVAP
    a_m = (tot_kg * R_MASH) + SM_MASH
    a_s = (v_pre + (tot_kg * ASS_G)) - a_m
    
    boil_gravity = (og - 1) * (litri_target / v_pre) if v_pre > 0 else 0
    f_gravity = 1.65 * (0.000125 ** boil_gravity)
    
    for l in luppoli:
        if l['tipo'] == "Boil":
            util = f_gravity * ((1 - math.exp(-0.04 * l['valore_tempo'])) / 4.15)
            tot_ibu += ((l['grammi'] * (l['aa'] / 100) * 1000) * util) / litri_target
        elif l['tipo'] == "Hopstand":
            util = f_gravity * 0.03
            tot_ibu += ((l['grammi'] * (l['aa'] / 100) * 1000) * util) / litri_target
            
    return og, v_pre, a_m, a_s, tot_kg, tot_ibu, fg, abv, tot_ebc

def ebc_to_hex(ebc):
    """Converte il valore EBC nel colore HEX corrispondente"""
    if ebc <= 4: return "#F3F9BE"
    elif ebc <= 8: return "#F6F510"
    elif ebc <= 16: return "#E0D01B"
    elif ebc <= 26: return "#CDAA37"
    elif ebc <= 39: return "#BE8C3A"
    elif ebc <= 59: return "#C17135"
    elif ebc <= 100: return "#462215"
    return "#080707"

def check_range(valore, v_min, v_max):
    """Confronto tra valore calcolato e range BJCP"""
    try:
        v_min, v_max = float(v_min), float(v_max)
        if v_min == 0 and v_max == 0: return "⚪", "gray", "n.d."
        if valore < v_min: return "⚠️", "#ff4b4b", f"Basso (min {v_min})"
        elif valore > v_max: return "⚠️", "#ff4b4b", f"Alto (max {v_max})"
        else: return "✅", "#28a745", "In stile"
    except: return "⚪", "gray", "errore dati"

def calcola_ripartizione_bottiglie(litri_netti):
    vol_075 = 9 * 0.75
    residuo = litri_netti - vol_075
    bot_066, bot_050 = 0, 0
    if residuo > 0:
        coppie = int(residuo // 3.48)
        bot_066, bot_050 = coppie * 3, coppie * 3
        residuo -= (coppie * 3.48)
        if residuo >= 1.98: bot_066 += 3; residuo -= 1.98
        elif residuo >= 1.50: bot_050 += 3; residuo -= 1.50
    return 9, bot_066, bot_050, max(0.0, residuo)

def ottimizza_pacchetti_malto(kg_necessari):
    if kg_necessari <= 0: return {}
    n25 = int(kg_necessari // 25); resto = kg_necessari % 25
    n5 = int(resto // 5); resto = resto % 5
    n1 = int(math.ceil(resto))
    res = {}
    if n25 > 0: res["Sacco 25kg"] = n25
    if n5 > 0: res["Sacco 5kg"] = n5
    if n1 > 0: res["Sacco 1kg"] = n1
    return res

def ottimizza_pacchetti_luppolo(g_necessari):
    if g_necessari <= 0: return {}
    n250 = int(g_necessari // 250); resto = g_necessari % 250
    if resto > 180: n250 += 1; resto = 0
    n100 = int(resto // 100); resto = resto % 100
    if resto > 70: n100 += 1; resto = 0
    n30 = int(math.ceil(resto / 30))
    res = {}
    if n250 > 0: res["Busta 250g"] = n250
    if n100 > 0: res["Busta 100g"] = n100
    if n30 > 0: res["Busta 30g"] = n30
    return res

def scala_ingredienti(nuovi_litri, vecchi_litri, fermentabili, luppoli):
    """Riscala le quantità in base ai nuovi litri target"""
    if vecchi_litri <= 0 or nuovi_litri == vecchi_litri:
        return fermentabili, luppoli
    ratio = nuovi_litri / vecchi_litri
    for f in fermentabili: f['kg'] = round(f['kg'] * ratio, 2)
    for l in luppoli: l['grammi'] = round(l['grammi'] * ratio, 1)
    return fermentabili, luppoli

# --- 5. FUNZIONE PDF SCHEDA ---
def genera_pdf_ricetta(nome, stile, litri, og, fg, abv, ibu, ebc, a_m, a_s, fermentabili, luppoli, lievito, mash_steps):
    pdf = FPDF()
    pdf.add_page()
    
    # --- REGISTRAZIONE FONT ---
    try:
        pdf.add_font('Freakshow', '', 'Carnevalee_Freakshow.ttf', uni=True)
        font_titolo = 'Freakshow'
    except:
        font_titolo = 'Helvetica'

    def clean(t):
        if not isinstance(t, str): t = str(t)
        return t.replace("’", "'").replace("“", '"').replace("”", '"').encode('latin-1', 'replace').decode('latin-1')

    # --- INTESTAZIONE NERO SU BIANCO ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_titolo, '', 45) 
    pdf.cell(0, 25, clean(nome.upper()), ln=True, align='C')
    
    # 2. STILE (Sempre nel tuo font, un po' più piccolo)
    pdf.set_font(font_titolo, '', 25) 
    testo_stile = f"Stile: {stile}" if stile else "Stile: Libero"
    pdf.cell(0, 15, clean(testo_stile), ln=True, align='C')
    
    # Linea di separazione elegante
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(10)

    # --- RIEPILOGO TECNICO ---
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 8, " PARAMETRI TECNICI", ln=True, fill=True)
    
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(38, 10, clean(f" OG: {og:.3f}"), border='LTB')
    pdf.cell(38, 10, clean(f" FG: {fg:.3f}"), border='TB')
    pdf.cell(38, 10, clean(f" ABV: {abv:.1f}%"), border='TB')
    pdf.cell(38, 10, clean(f" IBU: {ibu:.1f}"), border='TB')
    pdf.cell(38, 10, clean(f" EBC: {ebc:.1f}"), border='RTB', ln=True)
    pdf.ln(5)

    # Volumi Acqua
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 8, " VOLUMI ACQUA", ln=True, fill=True)
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(63, 10, clean(f" Mash: {a_m:.1f} L"), border=1)
    pdf.cell(63, 10, clean(f" Sparge: {a_s:.1f} L"), border=1)
    pdf.cell(64, 10, clean(f" Totale: {litri} L"), border=1, ln=True)
    pdf.ln(5)

    # Sezioni Ingredienti
    def sez(t, d, r, g, b):
        pdf.set_fill_color(r, g, b)
        pdf.set_font("Helvetica", 'B', 11)
        pdf.cell(0, 8, f" {t}", ln=True, fill=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", '', 10)
        if d:
            for item in d:
                pdf.cell(0, 7, clean(f"  > {item}"), ln=True)
        else:
            pdf.cell(0, 7, "  - Nessun dato", ln=True)
        pdf.ln(3)

    sez("MALTI E FERMENTABILI", [f"{f['nome']}: {f['kg']} kg" for f in fermentabili], 255, 245, 200)
    sez("LUPPOLI", [f"{l['tipo']}: {l['nome']} {l['grammi']}g ({l['valore_tempo']} min/gg)" for l in luppoli], 220, 240, 220)
    sez("LIEVITO", [f"{lievito['nome']}" if lievito else "Nessuno"], 240, 240, 240)
    sez("MASH", [f"{s['temp']} C per {s['tempo']} min" for s in mash_steps], 210, 230, 250)

    return bytes(pdf.output())

# --- 5b. NUOVA FUNZIONE PDF ETICHETTE (MODIFICATA) ---
def genera_pdf_etichette(nome, stile, abv, data_imb):
    from fpdf import FPDF
    import os

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    if os.path.exists("Carnevalee_Freakshow.ttf"):
        pdf.add_font("Carnivalee", "", "Carnevalee_Freakshow.ttf")
        font_main = "Carnivalee"
    else:
        font_main = "Helvetica"
    
    # Parametri di scala
    BASE_W, BASE_H = 62, 85
    w_et, h_et = 55, 73   # Dimensioni attuali
    scale = min(w_et / BASE_W, h_et / BASE_H)

    def s(v):
        return v * scale

    # Margini centrati
    m_x = (210 - (3 * w_et)) / 2
    m_y = (297 - (3 * h_et)) / 2

    for i in range(9):
        col = i % 3
        row = i // 3
        x = m_x + (col * w_et)
        y = m_y + (row * h_et)

        # Bordo etichetta
        pdf.set_line_width(1.4)
        pdf.rect(x, y, w_et, h_et)
        pdf.set_line_width(0.2)

        # 1. Logo Upper
        if os.path.exists("Logo Upper.png"):
            pdf.image("Logo Upper.png", x + s(4), y + s(3), w_et - s(8))

        # 2. Logo Medium (AUMENTATA DIMENSIONE p_w)
        if os.path.exists("Logo Medium.png"):
            p_w = s(35) # <--- Aumentato da 28 a 35
            pdf.image("Logo Medium.png", x + (w_et - p_w) / 2, y + s(14), p_w)

        # 3. EST 2021 (Commentato come da tua richiesta)
        pdf.set_font("Times", 'B', max(1, int(7 * scale)))
        pdf.set_xy(x, y + s(48))
        # pdf.cell(w_et, s(5), "EST. 2021", align='C')

        # 4. Nome birra (RIGA TITOLO - INGRANDITA)
        pdf.set_font(font_main, "", max(1, int(20 * scale))) # <--- Aumentato da 16 a 20
        pdf.set_xy(x, y + s(55)) # <--- Alzata la Y da 53 a 48 per dare spazio
        pdf.cell(w_et, s(10), nome.upper(), align='C')

        # --- 4. STILE (Allineato a sinistra) ---
        pdf.set_font(font_main, "", max(1, int(14 * scale)))
        # Usiamo x + 2 per distanziarlo leggermente dal bordo nero
        pdf.set_xy(x + 2, y + s(75)) 
        pdf.cell(s(30), s(10), stile.upper(), align='L')

        # --- 5. ABV (Allineato a destra) ---
        # Usiamo un font più grande come richiesto
        pdf.set_font(font_main, "", max(1, int(18 * scale)))
        # Posizioniamo la cella in modo che finisca a
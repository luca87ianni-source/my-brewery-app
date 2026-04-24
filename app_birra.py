import streamlit as st
import pandas as pd
import os
import math
import json
from datetime import date
from fpdf import FPDF
import google.generativeai as genai

# --- CARICAMENTO API KEY GEMINI ---
def get_api_key():
    if os.path.exists("key_gemini.txt"):
        with open("key_gemini.txt", "r") as f:
            return f.read().strip()
    return None

api_key = get_api_key()
if api_key:
    genai.configure(api_key=api_key)

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

# Caricamento rapido dei DataFrame dai JSON per popolare i menu a tendina e le tabelle
def inizializza_database():
    """Trasforma i file JSON in DataFrame all'avvio dell'app"""
    # Carichiamo i dati dai JSON usando la funzione carica_db definita nella Sezione 2
    df_f = pd.DataFrame(carica_db("malti")).T.reset_index().rename(columns={'index': 'Fermentabile'})
    df_l = pd.DataFrame(carica_db("luppoli")).T.reset_index().rename(columns={'index': 'Luppolo'})
    df_y = pd.DataFrame(carica_db("lieviti")).T.reset_index().rename(columns={'index': 'Lievito'})
    df_s = pd.DataFrame(carica_db("stili")).T.reset_index().rename(columns={'index': 'Stile'})
    return df_f, df_l, df_y, df_s

# Creazione dei DataFrame globali (Sostituisce il vecchio carica_database Excel)
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
    from fpdf import FPDF
    import os
    
    pdf = FPDF()
    pdf.add_page()
    
    # 1. DEFINIZIONE FUNZIONE CLEAN (Deve stare qui dentro!)
    def clean(t):
        if not isinstance(t, str): t = str(t)
        # Sostituisce caratteri speciali che FPDF non digerisce bene
        return t.replace("’", "'").replace("“", '"').replace("”", '"').encode('latin-1', 'replace').decode('latin-1')

    # 2. CARICAMENTO FONT
    font_path = "Carnevalee Freakshow.ttf"
    if os.path.exists(font_path):
        try:
            pdf.add_font("Freakshow", "", font_path)
            font_titolo = "Freakshow"
        except:
            font_titolo = "Helvetica"
    else:
        font_titolo = "Helvetica"

    # 3. INTESTAZIONE
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_titolo, '', 45) 
    pdf.cell(0, 25, clean(nome.upper()), ln=True, align='C')
    
    pdf.set_font(font_titolo, '', 25) 
    testo_stile = f"Stile: {stile}" if stile else "Stile: Libero"
    pdf.cell(0, 15, clean(testo_stile), ln=True, align='C')
    
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(10)

    # 4. PARAMETRI TECNICI
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

    # 5. VOLUMI ACQUA
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 8, " VOLUMI ACQUA", ln=True, fill=True)
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(63, 10, clean(f" Mash: {a_m:.1f} L"), border=1)
    pdf.cell(63, 10, clean(f" Sparge: {a_s:.1f} L"), border=1)
    pdf.cell(64, 10, clean(f" Totale: {litri} L"), border=1, ln=True)
    pdf.ln(5)

    # 6. SEZIONI INGREDIENTI
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

    # Piè di pagina
    pdf.set_y(-20)
    pdf.set_font("Helvetica", 'I', 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 10, f"Sons of Brewery - Ricetta: {nome}", align='C')

    # --- RITORNO BINARIO SICURO PER STREAMLIT CLOUD (fpdf2) ---
    # Al posto di return bytes(pdf.output())
    valore_pdf = pdf.output()
    if isinstance(valore_pdf, (bytes, bytearray)):
        return bytes(valore_pdf)
    return valore_pdf

# --- 5b. NUOVA FUNZIONE PDF ETICHETTE (MODIFICATA) ---
def genera_pdf_etichette(nome, stile, abv, data_imb):
    from fpdf import FPDF
    import os

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    # Funzione CLEAN per evitare crash su caratteri speciali
    def clean(t):
        if not isinstance(t, str): t = str(t)
        return t.replace("’", "'").replace("“", '"').replace("”", '"').encode('latin-1', 'replace').decode('latin-1')
    
    # Caricamento Font
    if os.path.exists("Carnevalee Freakshow.ttf"):
        try:
            pdf.add_font("Carnivalee", "", "Carnevalee Freakshow.ttf")
            font_main = "Carnivalee"
        except:
            font_main = "Helvetica"
    else:
        font_main = "Helvetica"
    
    # Parametri di scala (TUTTI ORIGINALI)
    BASE_W, BASE_H = 62, 85
    w_et, h_et = 55, 73
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

        # 2. Logo Medium
        if os.path.exists("Logo Medium.png"):
            p_w = s(35)
            pdf.image("Logo Medium.png", x + (w_et - p_w) / 2, y + s(14), p_w)

        # 3. EST 2021 (Mantenuto Times come originale)
        pdf.set_font("Times", 'B', max(1, int(7 * scale)))
        pdf.set_xy(x, y + s(48))
        # pdf.cell(w_et, s(5), "EST. 2021", align='C')

        # 4. Nome birra (RIGA TITOLO - COORDINATA ORIGINALE s(55))
        pdf.set_font(font_main, "", max(1, int(20 * scale)))
        pdf.set_xy(x, y + s(55)) # <--- RIPRISTINATA ORIGINALE
        pdf.cell(w_et, s(10), clean(nome.upper()), align='C')

        # --- 4. STILE (Allineato a sinistra) ---
        pdf.set_font(font_main, "", max(1, int(14 * scale)))
        pdf.set_xy(x + 2, y + s(75)) 
        pdf.cell(s(30), s(10), clean(stile.upper() if stile else "LIBERO"), align='L')

        # --- 5. ABV (Allineato a destra) ---
        pdf.set_font(font_main, "", max(1, int(18 * scale)))
        pdf.set_xy(x + w_et - s(15) - 2, y + s(75))
        pdf.cell(s(15), s(10), f"{abv:.1f}%", align='R')

        # 6. Icona Pregnant
        if os.path.exists("Pregnant.png"):
            pdf.image("Pregnant.png", x + s(2.5), y + s(64.5), s(6))

        # 7. Data imbottigliamento (Rotazione originale)
        pdf.set_font("Times", "", max(1, int(7 * scale)))
        with pdf.rotation(90, x + w_et - s(1.5), y + s(55)):
            pdf.text(x + w_et - s(1.5), y + s(55), clean(f"Imbottigliata il {data_imb}"))

    # --- RITORNO BINARIO SICURO PER STREAMLIT CLOUD (fpdf2) ---
    # Al posto di return bytes(pdf.output())
    valore_pdf = pdf.output()
    if isinstance(valore_pdf, (bytes, bytearray)):
        return bytes(valore_pdf)
    return valore_pdf

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
    
    # NUOVO PULSANTE DATABASE (Punto 2 del tuo piano)
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
            
# --- 8. PAGINA EDITOR (VERSIONE INTEGRALE E CORRETTA) ---
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
        vol_default = float(s_info.get('Volumi', 2.3))
    
    # --- 2. RECUPERO VOLUMI CO2 (GESTIONE ERRORE KEYERROR) ---
    vol_default = 2.3
    if st.session_state.stile_b and not df_s_m.empty:
        s_info = df_s_m[df_s_m["Stile"] == st.session_state.stile_b]
        if not s_info.empty:
            # Controlla se esiste Vol_CO2 o Volumi nel JSON
            colonne = s_info.columns
            colonna_target = "Vol_CO2" if "Vol_CO2" in colonne else ("Volumi" if "Volumi" in colonne else None)
            
            if colonna_target:
                try:
                    val = float(s_info[colonna_target].values[0])
                    vol_default = val if val > 0 else 2.3
                except:
                    vol_default = 2.3

    # --- 3. CALCOLO COSTI (PUNTANDO AL MAGAZZINO JSON) ---
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

    # TILE VERDE COSTI (Sotto le rilevazioni come nel tuo vecchio codice)
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
            st.session_state.f_list.append({'nome': s_f, 'kg': k_f, 'ppg': float(d['PPG']), 'ebc': float(d['EBC'])})
            st.rerun()
        for i, it in enumerate(st.session_state.f_list):
            c = st.columns([0.9, 0.1]); c[0].markdown(f'<div class="ingrediente-box">{it["nome"]} - {it["kg"]:.2f}kg</div>', unsafe_allow_html=True)
            if c[1].button("❌", key=f"del_f_{i}"): st.session_state.f_list.pop(i); st.rerun()

    with t2:
        l1, l2, l3 = st.columns([2, 1, 1])
        s_l = l1.selectbox("LUPPOLO", [""] + sorted(df_l_m["Luppolo"].tolist()), key="sel_l_ed")
        g_l = l2.number_input("Grammi", step=1.0, key="qta_l_ed")
        t_l = l3.selectbox("Modalità", ["Boil", "Hopstand", "Dry Hop"], key="mod_l_ed")
        
        c_val1, _ = st.columns(2)
        val_p = 60
        if t_l == "Boil": val_p = c_val1.number_input("Minuti", value=60, key="v_boil")
        elif t_l == "Hopstand": val_p = c_val1.number_input("Temp °C", value=80, key="v_hop")
        else: val_p = c_val1.number_input("Giorni", value=3, key="v_dry")

        if st.button("➕ Aggiungi Luppolo") and s_l and g_l > 0:
            d = df_l_m[df_l_m["Luppolo"] == s_l].iloc[0]
            st.session_state.l_list.append({'nome': s_l, 'grammi': g_l, 'tipo': t_l, 'valore_tempo': val_p, 'aa': float(d['Alfa acidi (%)'])})
            st.rerun()
        for i, it in enumerate(st.session_state.l_list):
            c = st.columns([0.9, 0.1]); suf = "min" if it['tipo']=="Boil" else ("°C" if it['tipo']=="Hopstand" else "gg")
            c[0].markdown(f'<div class="ingrediente-box"><b>{it["tipo"]}</b>: {it["nome"]} {it["grammi"]:.0f}g @ {it["valore_tempo"]}{suf}</div>', unsafe_allow_html=True)
            if c[1].button("🗑️", key=f"del_l_{i}"): st.session_state.l_list.pop(i); st.rerun()

    with t3:
        sel_y = st.selectbox("LIEVITO", [""] + sorted(df_y_m["Lievito"].tolist()))
        if st.button("CONFERMA LIEVITO") and sel_y:
            dy = df_y_m[df_y_m["Lievito"] == sel_y].iloc[0]
            st.session_state.yeast_sel = {'nome': sel_y, 'attenuazione': float(dy['Attenuazione (%)'])}; st.rerun()
        if st.session_state.yeast_sel: st.info(f"Selezionato: {st.session_state.yeast_sel['nome']}")

    with t4:
        m1, m2 = st.columns(2); tm, tmin = m1.number_input("Temp °C", value=65), m2.number_input("Minuti", value=60)
        if st.button("➕ Step Mash"): st.session_state.m_list.append({'temp': tm, 'tempo': tmin}); st.rerun()
        for i, s_mash in enumerate(st.session_state.m_list):
            c = st.columns([0.9, 0.1]); c[0].markdown(f'<div class="ingrediente-box">{s_mash["temp"]}°C per {s_mash["tempo"]} min</div>', unsafe_allow_html=True)
            if c[1].button("🗑️", key=f"del_m_{i}"): st.session_state.m_list.pop(i); st.rerun()

    # --- 6. PRIMING E BOTTIGLIE ---
    st.divider(); st.subheader("🍬 CALCOLO ZUCCHERO DI PRIMING")
    col_p1, col_p2, col_p3 = st.columns(3)
    v_co2 = col_p1.number_input("Vol CO2", value=vol_default, step=0.1)
    t_fer = col_p2.number_input("Temp Max (°C)", value=20.0)
    l_net = col_p3.number_input("Litri netti", value=float(st.session_state.litri_f - 2.0))
    
    zuc = max(0.0, (v_co2 - (1.57 * pow(0.982, t_fer))) * 4.0 * l_net)
    
    st.markdown(f"""<div class="calc-box" style="background-color: #4A90E2; color: white !important;"><div style="display:flex; justify-content:space-around; text-align:center;">
            <div><div class="metric-label" style="color:white !important;">Zucchero Totale</div><div class="metric-value" style="color:white !important;">{zuc:.1f} g</div></div>
            <div><div class="metric-label" style="color:white !important;">Gr/Litro</div><div class="metric-value" style="color:white !important;">{(zuc/l_net if l_net>0 else 0):.2f} g/L</div></div>
        </div></div>""", unsafe_allow_html=True)

    st.divider(); st.subheader("🍾 PIANIFICAZIONE IMBOTTIGLIAMENTO")
    try:
        b75, b66, b50, scolo = calcola_ripartizione_bottiglie(l_net)
        q75, q66, q50 = b75 // 3, b66 // 3, b50 // 3
        cb1, cb2, cb3, cb4 = st.columns(4)
        cb1.metric("0.75 L", f"{b75}", delta=f"{q75} a testa")
        cb2.metric("0.66 L", f"{b66}", delta=f"{q66} a testa")
        cb3.metric("0.50 L", f"{b50}", delta=f"{q50} a testa")
        cb4.metric("RESIDUO", f"{scolo:.2f} L")
    except:
        st.warning("Funzione calcolo bottiglie non caricata.")

    # --- 7. PULSANTI AZIONE ---
    st.divider(); col_salva, col_carrello, col_scarica = st.columns(3)
    if col_salva.button("💾 SALVA IN ARCHIVIO", use_container_width=True):
        salva_su_file(st.session_state.nome_b, st.session_state.stile_b, st.session_state.data_imb, st.session_state.litri_f, st.session_state.f_list, st.session_state.l_list, st.session_state.yeast_sel, st.session_state.m_list, st.session_state.og_reale, st.session_state.fg_reale, st.session_state.abv_reale)
        st.toast("Salvata con successo!")
    
    if col_carrello.button("🛒 AGGIUNGI AL CARRELLO", use_container_width=True):
        tutti = st.session_state.f_list + st.session_state.l_list
        if st.session_state.yeast_sel: tutti.append({'nome': st.session_state.yeast_sel['nome'], 'lievito': True})
        aggiungi_a_shopping_list(tutti); st.success("Aggiunti al carrello!")
    
    if col_scarica.button("🍺 SCARICA DAL MAGAZZINO", type="primary", use_container_width=True):
        for f_item in st.session_state.f_list: aggiorna_scorta("Fermentabili", f_item['nome'], f_item['kg'], operazione="sub")
        for l_item in st.session_state.l_list: aggiorna_scorta("Luppoli", l_item['nome'], l_item['grammi'], operazione="sub")
        if st.session_state.yeast_sel: aggiorna_scorta("Lieviti", st.session_state.yeast_sel['nome'], 1, operazione="sub")
        st.success("Magazzino aggiornato!")
    
    # PDF e Etichette
    st.divider()
    cd1, cd2 = st.columns(2)
    with cd1:
        # Generiamo il PDF usando la nuova funzione (che deve essere definita prima nel codice)
        pdf_ricetta = genera_pdf_ricetta(
            st.session_state.nome_b, 
            st.session_state.stile_b, 
            st.session_state.litri_f, 
            og, 
            fg, 
            abv, 
            ibu, 
            ebc, 
            a_m, 
            a_s, 
            st.session_state.f_list, 
            st.session_state.l_list, 
            st.session_state.yeast_sel, 
            st.session_state.m_list
        )
        
        # Bottone di download che punta ai dati appena generati
        st.download_button(
            label="📄 SCHEDA PDF", 
            data=pdf_ricetta, 
            file_name=f"Scheda_{st.session_state.nome_b}.pdf", 
            mime="application/pdf", 
            use_container_width=True
        )
    with cd2:
        pdf_etichette = genera_pdf_etichette(st.session_state.nome_b, st.session_state.stile_b, st.session_state.abv_reale, st.session_state.data_imb.strftime("%d/%m/%Y"))
        st.download_button("🏷️ ETICHETTE PDF", data=pdf_etichette, file_name=f"Etichette_{st.session_state.nome_b}.pdf", mime="application/pdf", use_container_width=True)

# --- 10. PAGINA AGENTE AI (AIGOR) ---
elif st.session_state.pagina == "AIGOR":   
    # TITOLO CON NOME PERSONALIZZATO
    nome_agente = "AIgor" 
    
    st.markdown(f"""
        <div style="text-align: center; padding: 10px; border-radius: 10px; background-color: #ffd700; margin-bottom: 20px;">
            <h1 style="color: #000000; margin: 0; font-family: 'Carnivalee', sans-serif;">🤖 {nome_agente}</h1>
            <p style="color: #000000; font-weight: bold; margin: 0;">L'INTELLIGENZA DEI SONS OF BREWERY</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.info(f"Ciao sono {nome_agente}. Fammi vedere cosa hai in magazzino e vediamo che birra possiamo tirar fuori.")
    
    if not api_key:
        st.error("⚠️ Chiave API non trovata nel file key_gemini.txt. Controlla il file!")
        st.stop()

    mag = carica_magazzino()

    # --- PANNELLO DI CONTROLLO ---
    with st.container(border=True):
        st.subheader("🎯 Parametri di Ottimizzazione")
        c1, c2 = st.columns(2)
        
        with c1:
            direzioni = st.multiselect(
                "Direzioni Aromatiche desiderate:",
                options=["Luppolata/Tropicale", "Maltata/Dolce", "Tostata/Torrefatta", "Belga/Speziata", "Classica/Pilsner", "Strong/Alcolica"],
                help="Scegliendo più direzioni, l'AI capirà se deve smistare gli ingredienti in più cotte separate."
            )
            solo_lievito = st.toggle("Usa solo lieviti in magazzino", value=True)
        
        with c2:
            abv_range = st.select_slider(
                "Range Alcolico desiderato (ABV %)",
                options=[f"{x/10:.1f}" for x in range(30, 130, 5)],
                value=("4.5", "7.5")
            )
            priorita = st.radio("Priorità:", ["Svuota più magazzino possibile", "Massima fedeltà allo stile"], horizontal=True)

    # --- LOGICA DI GENERAZIONE ---
    if st.button("🚀 GENERA STRATEGIA RICETTE", use_container_width=True):
        # Costruiamo il contesto tecnico del magazzino leggendo dal JSON
        scorte_info = ""
        for cat in ["Fermentabili", "Luppoli", "Lieviti"]:
            scorte_info += f"\n{cat.upper()}:\n"
            for n, d in mag.get(cat, {}).items():
                u = "kg" if cat=="Fermentabili" else "g" if cat=="Luppoli" else "unità"
                scorte_info += f"- {n}: {d['qta']} {u}\n"

        prompt_sistema = f"""
        Sei {nome_agente}, un homebrewer esperto dei Sons of Brewery. 
        Sei competente ma alla mano: parli come uno che ha fatto tante cotte, senza fare il professore.

        SCORTE ATTUALI: {scorte_info}
        
        PARAMETRI TECNICI:
        - Direzioni: {', '.join(direzioni) if direzioni else 'Fai tu, basta che sia buona'}
        - Vincolo Lievito: {solo_lievito} (Se non ne ha, digli chiaramente cosa comprare senza fare il professore)
        - Range ABV: {abv_range[0]}% - {abv_range[1]}%
        - Strategia: {priorita}
        
        REGOLE DI RISPOSTA (Sii conciso!):
        1. Vai dritto al punto. Se il magazzino è vuoto, dillo senza giri di parole. 
        2. Presenta la RICETTA COMPLETA (23L) in un unico blocco tecnico unificato.
        3. Per ogni ingrediente scrivi chiaramente: "Nome | Totale | (Quantità dalle scorte + Quantità da comprare)".
        4. Sezione "NOTE RAPIDE" solo per Mash, Luppolatura e Lievito.
        5. Se proponi più cotte, separale con una linea netta.
        6. Firma come un vero duro dei Sons.
        """
        
        with st.spinner("Sto pensando..."):
            try:
                model = genai.GenerativeModel("gemini-2.5-flash")
                response = model.generate_content(prompt_sistema)
                st.session_state.chat_history = [{"role": "assistant", "content": response.text}]
            except Exception as e:
                st.error(f"Errore: {e}")

    # --- INTERAZIONE E CHAT DI RIFINITURA ---
    st.divider()
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt_utente := st.chat_input("Chiedi modifiche (es: 'Più amara', 'Cambia stile')"):
        st.session_state.chat_history.append({"role": "user", "content": prompt_utente})
        with st.chat_message("user"): st.markdown(prompt_utente)
        
        with st.chat_message("assistant"):
            with st.spinner("Ricalcolo in corso..."):
                model = genai.GenerativeModel("gemini-2.5-flash")
                # Forniamo il magazzino nel contesto per coerenza
                context_with_query = f"Giacenze magazzino: {mag}. Conversazione precedente: {st.session_state.chat_history}. Richiesta utente: {prompt_utente}"
                response = model.generate_content(context_with_query)
                st.markdown(response.text)
                st.session_state.chat_history.append({"role": "assistant", "content": response.text})

    if st.session_state.chat_history:
        if st.button("🗑️ Reset Analisi"):
            st.session_state.chat_history = []
            st.rerun()

# ========================================================
# --- 9. GESTIONE PAGINE FINALI (DATABASE & HOME) ---
# ========================================================


# --- PAGINA DATABASE (VERSIONE COMPLETA CON STILI) ---
elif st.session_state.pagina == "Database":
    st.markdown("""
        <style>
        div[data-testid="stForm"] button {
            background-color: #ffd700 !important;
            color: #000000 !important;
            border: 2px solid #000000 !important;
            font-weight: bold !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🗄️ Gestione Database")
    
    tab_db1, tab_db2, tab_db3, tab_db4 = st.tabs(["🌾 Fermentabili", "🌿 Luppoli", "🧫 Lieviti", "🏆 Stili BJCP"])

    # ... (Manteniamo i tab 1, 2 e 3 come prima) ...

    with tab_db1:
        st.subheader("Aggiungi Malto")
        with st.form("form_malti"):
            nome_f = st.text_input("Nome Malto")
            c1, c2 = st.columns(2)
            ppg_f = c1.number_input("PPG", value=36.0)
            ebc_f = c2.number_input("EBC", value=10.0)
            if st.form_submit_button("REGISTRA MALTO"):
                if nome_f:
                    nuovo = pd.DataFrame([{"Fermentabile": nome_f, "PPG": ppg_f, "EBC": ebc_f}])
                    df_f_m = pd.concat([df_f_m, nuovo], ignore_index=True).drop_duplicates(subset="Fermentabile")
                    df_f_m.to_json("ingredienti_f.json", orient="records", indent=4)
                    st.success(f"{nome_f} salvato!")
                    st.rerun()
        st.dataframe(df_f_m, use_container_width=True, hide_index=True)

    with tab_db2:
        st.subheader("Aggiungi Luppolo")
        with st.form("form_luppoli"):
            nome_l = st.text_input("Nome Luppolo")
            c_l1, c_l2 = st.columns(2)
            aa_l = c_l1.number_input("Alfa Acidi (%)", value=5.0)
            tipo_l = c_l2.selectbox("Tipo Luppolo", ["Amaro", "Aroma", "Duale"])
            if st.form_submit_button("REGISTRA LUPPOLO"):
                if nome_l:
                    nuovo_l = pd.DataFrame([{"Luppolo": nome_l, "Alfa acidi (%)": aa_l, "Tipo": tipo_l}])
                    df_l_m = pd.concat([df_l_m, nuovo_l], ignore_index=True).drop_duplicates(subset="Luppolo")
                    df_l_m.to_json("ingredienti_l.json", orient="records", indent=4)
                    st.success(f"{nome_l} salvato!")
                    st.rerun()
        st.dataframe(df_l_m, use_container_width=True, hide_index=True)

    with tab_db3:
        st.subheader("Aggiungi Lievito")
        with st.form("form_lieviti"):
            nome_y = st.text_input("Nome Lievito")
            att_y = st.number_input("Attenuazione (%)", value=75.0)
            if st.form_submit_button("REGISTRA LIEVITO"):
                if nome_y:
                    nuovo_y = pd.DataFrame([{"Lievito": nome_y, "Attenuazione (%)": att_y}])
                    df_y_m = pd.concat([df_y_m, nuovo_y], ignore_index=True).drop_duplicates(subset="Lievito")
                    df_y_m.to_json("ingredienti_y.json", orient="records", indent=4)
                    st.success(f"{nome_y} salvato!")
                    st.rerun()
        st.dataframe(df_y_m, use_container_width=True, hide_index=True)

    # --- VERSIONE DEFINITIVA E COMPLETA STILI BJCP ---
    with tab_db4:
        st.subheader("Aggiungi Stile BJCP")
        with st.form("form_stili"):
            nome_s = st.text_input("Nome Stile (es: American IPA)")
            
            # 6 colonne per far stare tutto su una riga (OG, FG, IBU, EBC, ABV, VOL)
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            
            og_min = c1.number_input("OG Min", value=1.040, format="%.3f")
            og_max = c1.number_input("OG Max", value=1.050, format="%.3f")
            
            fg_min = c2.number_input("FG Min", value=1.008, format="%.3f")
            fg_max = c2.number_input("FG Max", value=1.012, format="%.3f")
            
            ibu_min = c3.number_input("IBU Min", value=20.0, step=1.0)
            ibu_max = c3.number_input("IBU Max", value=40.0, step=1.0)
            
            ebc_min = c4.number_input("EBC Min", value=5.0, step=1.0)
            ebc_max = c4.number_input("EBC Max", value=15.0, step=1.0)
            
            abv_min = c5.number_input("ABV Min %", value=4.5, step=0.1, format="%.1f")
            abv_max = c5.number_input("ABV Max %", value=6.0, step=0.1, format="%.1f")

            # NUOVO: VOLUMI CO2 (Singolo valore di riferimento)
            vol_co2 = c6.number_input("Vol. CO2", value=2.4, step=0.1, format="%.1f")
            c6.caption("Target carbonazione")
            
            if st.form_submit_button("REGISTRA NUOVO STILE"):
                if nome_s:
                    nuovo_s = pd.DataFrame([{
                        "Stile": nome_s,
                        "OG_min": og_min, "OG_max": og_max,
                        "FG_min": fg_min, "FG_max": fg_max,
                        "IBU_min": ibu_min, "IBU_max": ibu_max,
                        "EBC_min": ebc_min, "EBC_max": ebc_max,
                        "ABV_min": abv_min, "ABV_max": abv_max,
                        "Vol_CO2": vol_co2
                    }])
                    
                    # Unione e salvataggio su JSON
                    df_s_m = pd.concat([df_s_m, nuovo_s], ignore_index=True).drop_duplicates(subset="Stile")
                    df_s_m.to_json("ingredienti_s.json", orient="records", indent=4)
                    st.success(f"✅ Stile {nome_s} registrato con successo!")
                    st.rerun()
        
        st.divider()
        st.dataframe(df_s_m.sort_values("Stile"), use_container_width=True, hide_index=True)

    if st.button("⬅️ TORNA ALLA HOME", use_container_width=True):
        st.session_state.pagina = "Home"
        st.rerun()

# --- B. DASHBOARD (HOME) - DEVE ESSERE SEMPRE L'ULTIMA ---
else:
    st.title("🦅 Dashboard")
    mag = carica_magazzino()
    arch = carica_archivio()
    
    # Calcolo metriche rapide dai dati JSON
    kg_malti = sum(float(i.get("qta", 0.0)) for i in mag["Fermentabili"].values())
    n_lupp = len(mag["Luppoli"])
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="calc-box"><div class="metric-label">Archivio</div><div class="metric-value">{len(arch)}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="calc-box"><div class="metric-label">Stock Malti</div><div class="metric-value">{kg_malti:.1f} Kg</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="calc-box"><div class="metric-label">Tipologie Luppoli</div><div class="metric-value">{n_lupp}</div></div>', unsafe_allow_html=True)

    st.subheader("⚠️ Monitoraggio Scorte")
    col_a1, col_a2 = st.columns(2)
    
    with col_a1:
        st.markdown("#### 🌾 Alert Malti")
        f_ok = True
        for n, d in mag["Fermentabili"].items():
            q = float(d.get("qta", 0.0))
            n_up = n.upper()
            soglia = 6.0 if ("PILSNER" in n_up or "PALE ALE" in n_up or "MARIS" in n_up) else 1.0
            if q < soglia:
                st.markdown(f'<div class="calc-box-alert">🚨 <b>{n}</b>: {q:.1f}kg</div>', unsafe_allow_html=True)
                f_ok = False
        if f_ok: st.success("Malti ok.")
            
    with col_a2:
        st.markdown("#### 🌿 Alert Luppoli")
        l_ok = True
        for n, d in mag["Luppoli"].items():
            q = float(d.get("qta", 0.0))
            if q < 30.0:
                st.markdown(f'<div class="calc-box-alert">🚨 <b>{n}</b>: {q:.0f}g</div>', unsafe_allow_html=True)
                l_ok = False
        if l_ok: st.success("Luppoli ok.")
    
    st.divider()
    sh1, sh2, sh3 = st.columns(3) 
    
    if sh1.button("➕ NUOVA RICETTA", use_container_width=True):
        st.session_state.nome_b = "Nuova Ricetta"
        st.session_state.stile_b = ""
        st.session_state.f_list, st.session_state.l_list, st.session_state.m_list = [], [], []
        st.session_state.yeast_sel = None
        st.session_state.og_reale, st.session_state.fg_reale = 1.050, 1.010
        st.session_state.pagina = "Editor"
        st.rerun()
        
    if sh2.button("📦 VAI AL MAGAZZINO", use_container_width=True): 
        st.session_state.pagina = "Magazzino"
        st.rerun()
        
    if sh3.button("🤖 PARLA CON AIGOR", use_container_width=True): 
        st.session_state.pagina = "AIGOR"
        st.rerun()


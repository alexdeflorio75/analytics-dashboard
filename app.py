import streamlit as st
import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension
from google.oauth2 import service_account
import google.generativeai as genai
import os
import datetime
import streamlit.components.v1 as components
import altair as alt 
import json
import re
import urllib.parse
import base64

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Report Analitico", layout="wide", page_icon="📊")

# --- 2. GESTIONE PARAMETRI URL E AUTO-RUN ---
# Questa sezione DEVE stare all'inizio per intercettare il link
query_params = st.query_params
url_id = query_params.get("id", "")
url_client = query_params.get("client", "")
url_context = query_params.get("context", "")

# Inizializza session state
if 'report_data' not in st.session_state:
    st.session_state.report_data = None
if 'auto_run_triggered' not in st.session_state:
    st.session_state.auto_run_triggered = False

# Modalità "Stampa Pulita" (Toggle)
if 'print_mode' not in st.session_state:
    st.session_state.print_mode = False

def toggle_print_mode():
    st.session_state.print_mode = not st.session_state.print_mode

# --- 3. CSS DESIGN & CLEAN MODE ---
# Se siamo in print_mode, nascondiamo TUTTA l'interfaccia di Streamlit
css_logic = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Poppins:wght@600;700&display=swap');
    
    /* Font Base */
    html, body, p, div, label, .stMarkdown { font-family: 'Lato', sans-serif !important; color: #2D3233 !important; }
    h1, h2, h3, h4 { font-family: 'Poppins', sans-serif !important; color: #0D0D0D !important; }
    
    /* Input Style */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important; border: 1px solid #066C9C !important; border-radius: 4px;
    }
    
    /* Pulsanti */
    div.stButton > button:first-child {
        background-color: #D15627 !important; color: white !important; border: none; font-weight: bold;
    }

    /* --- MODALITÀ STAMPA (NASCONDE LA SIDEBAR SE ATTIVA) --- */
"""

if st.session_state.print_mode:
    css_logic += """
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stHeader"] { display: none !important; }
    .stDeployButton { display: none !important; }
    #MainMenu { display: none !important; }
    footer { display: none !important; }
    
    /* Nascondi i pulsanti di controllo nel report pulito */
    .no-print { display: none !important; }
    
    .block-container {
        padding-top: 0rem !important;
        max-width: 100% !important;
    }
    """

css_logic += "</style>"
st.markdown(css_logic, unsafe_allow_html=True)

# Funzione Logo
def get_base64_logo():
    if os.path.exists("logo.png"):
        with open("logo.png", "rb") as f: data = f.read()
        return base64.b64encode(data).decode()
    return ""
logo_b64 = get_base64_logo()

# --- 4. FUNZIONI CORE (AI, AUTH, DATA) ---
def configure_ai():
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
            return True
        return False
    except: return False

ai_configured = configure_ai()

def ask_gemini_advanced(df, report_name, kpi_curr, kpi_prev, comparison_active, business_context):
    if not ai_configured: return "⚠️ Analisi AI non disponibile."
    data_preview = df.head(10).to_string(index=False)
    ctx = f"Settore: {business_context}" if business_context else ""
    prompt = f"Analista Marketing. {ctx}. Report: {report_name}. Dati: {data_preview}. Analisi sintetica trend e consiglio operativo. No saluti."
    try:
        model = genai.GenerativeModel('gemini-3-pro-preview')
        return model.generate_content(prompt).text
    except:
        return "⚠️ Errore connessione AI."

def get_ga4_client():
    try:
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"], strict=False)
            return BetaAnalyticsDataClient(credentials=service_account.Credentials.from_service_account_info(creds_dict))
        elif os.path.exists('credentials.json'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
            return BetaAnalyticsDataClient()
        return None
    except: return None

def get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active, retry=False):
    client = get_ga4_client()
    if not client: return "AUTH_ERROR", None, None
    
    # Mappe semplificate per brevità
    dims = [Dimension(name="date")]
    mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]
    
    # Logica dimensioni (Compatta)
    if "Traffico" in report_kind: dims = [Dimension(name="sessionSourceMedium")]
    elif "Eventi" in report_kind: dims = [Dimension(name="eventName")]; mets = [Metric(name="eventCount")]
    elif "Pagine" in report_kind: dims = [Dimension(name="pageTitle")]
    elif "Monetizzazione" in report_kind:
        if not retry: dims = [Dimension(name="itemName")]; mets = [Metric(name="itemRevenue")]
        else: dims = [Dimension(name="date")]; mets = [Metric(name="totalRevenue")]
    
    try:
        req = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=start, end_date=end)], dimensions=dims, metrics=mets)
        res = client.run_report(req)
        
        # Parsing rapido
        data = []
        for row in res.rows:
            d = {'Dimensione': row.dimension_values[0].value}
            d['Valore'] = float(row.metric_values[0].value) if row.metric_values else 0
            data.append(d)
        df = pd.DataFrame(data)
        
        curr, prev = df['Valore'].sum(), 0
        if comp_active:
            req_p = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=p_start, end_date=p_end)], dimensions=dims, metrics=mets)
            res_p = client.run_report(req_p)
            for row in res_p.rows: prev += float(row.metric_values[0].value)
            
        return "OK", df, (curr, prev)
    except Exception as e:
        if "Monetizzazione" in report_kind and not retry: return get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active, True)
        return "ERROR", str(e), None

def render_chart(df, kind):
    if df.empty: return
    if "Eventi" in kind or "Acquisizione" in kind:
        st.bar_chart(df.set_index("Dimensione")['Valore'])
    else:
        st.line_chart(df.set_index("Dimensione")['Valore'])

def run_analysis_cycle(pid, cli, ctx, d_opt, reports):
    # Logica date
    today = datetime.date.today()
    if d_opt == "Ultimi 28 Giorni": start = today - datetime.timedelta(days=28)
    else: start = today - datetime.timedelta(days=90)
    end = today
    
    p_end = start - datetime.timedelta(days=1)
    p_start = p_end - (end - start)
    
    s_s, s_e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    p_s, p_e = p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d")
    
    results = {}
    for rep in reports:
        status, df, kpi = get_ga4_data(pid, s_s, s_e, p_s, p_e, rep, True)
        if status == "OK":
            comm = ask_gemini_advanced(df, rep, {rep: kpi[0]}, {rep: kpi[1]}, True, ctx)
            results[rep] = {"df": df, "kpi": kpi, "comm": comm}
    return results

# --- 5. INTERFACCIA UTENTE ---

# LOGICA AUTO-RUN: Se ci sono parametri URL e non abbiamo ancora dati, eseguiamo subito!
if url_id and url_client and st.session_state.report_data is None:
    with st.spinner(f"Generazione report automatico per {url_client}..."):
        # Default report list per auto-run
        defaults = ["Panoramica Trend", "Acquisizione Traffico"]
        st.session_state.report_data = run_analysis_cycle(url_id, url_client, url_context, "Ultimi 28 Giorni", defaults)
        st.session_state.last_client = url_client
        st.session_state.last_ctx = url_context

# SIDEBAR (Visibile solo se non in stampa)
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=80)
    st.markdown("### Configurazione")
    
    # Pre-compilazione dai parametri URL
    val_client = url_client if url_client else ""
    val_id = url_id if url_id else st.session_state.get('last_prop_id', '')
    val_ctx = url_context if url_context else ""
    
    client_name = st.text_input("Cliente", value=val_client)
    property_id = st.text_input("ID GA4", value=val_id)
    business_context = st.text_area("Contesto", value=val_ctx)
    
    st.divider()
    date_opt = st.selectbox("Periodo", ["Ultimi 28 Giorni", "Ultimi 90 Giorni"])
    
    grp = ["Panoramica Trend", "Acquisizione Traffico", "Monetizzazione", "Eventi"]
    sel_grp = st.multiselect("Seleziona Report", grp, default=["Panoramica Trend"])
    
    if st.button("🚀 GENERA REPORT"):
        if property_id:
            st.session_state.last_prop_id = property_id
            st.session_state.last_client = client_name
            st.session_state.last_ctx = business_context
            st.session_state.report_data = run_analysis_cycle(property_id, client_name, business_context, date_opt, sel_grp)
            st.rerun()

    # Link Generator
    if property_id and client_name:
        st.divider()
        safe_c = urllib.parse.quote(client_name)
        safe_ctx = urllib.parse.quote(business_context)
        # USA IL DOMINIO REALE ORA
        base = "https://analytics.alessandrodeflorio.it"
        link = f"{base}/?id={property_id}&client={safe_c}&context={safe_ctx}"
        st.text_input("Link Condivisione:", link)

# --- CORPO PRINCIPALE ---

# Intestazione Report (Sempre visibile)
c_name = st.session_state.get('last_client', client_name)
ctx_txt = st.session_state.get('last_ctx', business_context)

# HEADER CON LOGO E DATI
col_a, col_b = st.columns([1, 4])
with col_a:
    if os.path.exists("logo.png"):
        st.markdown(f'<img src="data:image/png;base64,{logo_b64}" width="100%">', unsafe_allow_html=True)
with col_b:
    st.title(f"Report: {c_name}")
    st.markdown(f"**Contesto:** {ctx_txt}")
    st.caption(f"Data Report: {datetime.date.today().strftime('%d/%m/%Y')}")

st.markdown("---")

# PULSANTIERA (Nascosta in stampa via CSS)
col_btn1, col_btn2 = st.columns([1, 5])
with col_btn1:
    if st.session_state.print_mode:
        if st.button("🔙 Torna all'Editor", key="back_btn"):
            toggle_print_mode()
            st.rerun()
    else:
        if st.button("🖨️ VERSIONE STAMPABILE", key="print_btn"):
            toggle_print_mode()
            st.rerun()

# CONTENUTO REPORT
if st.session_state.report_data:
    if st.session_state.print_mode:
        st.info("💡 ISTRUZIONI: Ora premi CRTL+P (o CMD+P) sulla tastiera. Il layout è pulito e pronto per il PDF.")
        st.markdown("<br>", unsafe_allow_html=True)

    data = st.session_state.report_data
    for name, content in data.items():
        st.markdown(f"### 📌 {name}")
        
        # KPI Semplificati
        curr, prev = content['kpi']
        delta = ((curr - prev) / prev * 100) if prev > 0 else 0
        st.metric("Valore Totale", f"{curr:,.0f}", f"{delta:.1f}%")
        
        st.markdown(f"**Analisi AI:** {content['comm']}")
        render_chart(content['df'], name)
        
        # Tabella (Solo se non siamo in stampa per risparmiare inchiostro/spazio, o opzionale)
        if not st.session_state.print_mode:
            with st.expander("Dati"): st.dataframe(content['df'])
        
        st.markdown("---")

elif not url_id:
    st.info("👈 Configura il report nella barra laterale.")

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

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="ADF Marketing Analyst", layout="wide", page_icon="📊")

if 'report_data' not in st.session_state:
    st.session_state.report_data = None

# --- 2. DESIGN SYSTEM (PALETTE FIX & INPUT VISIBILI) ---
st.markdown("""
<style>
    /* Import Font */
    @import url('https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Poppins:wght@600;700&display=swap');

    /* --- GLOBAL STYLES --- */
    .stApp {
        background-color: #F9F9F9; /* Grigio chiarissimo di sfondo */
    }
    
    html, body, p, div, label, .stMarkdown {
        font-family: 'Lato', sans-serif !important;
        color: #2D3233 !important; /* Testo scuro */
    }
    
    h1, h2, h3, h4 {
        font-family: 'Poppins', sans-serif !important;
        color: #0D0D0D !important; /* Titoli Neri */
    }

    /* --- INPUT FIELDS (FIX BORDI & CONTRASTO) --- */
    /* Caselle di testo e Selectbox */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        border: 1px solid #066C9C !important; /* Bordo Blu Palette */
        border-radius: 6px !important;
        color: #2D3233 !important;
    }
    
    /* Testo dentro gli input */
    input.stTextInput, .stSelectbox div {
        color: #2D3233 !important;
        font-weight: 500;
    }

    /* Label sopra gli input (es. "ID Proprietà") */
    .stTextInput label, .stSelectbox label, .stTextArea label {
        color: #066C9C !important; /* Blu Palette */
        font-weight: bold;
    }

    /* --- PULSANTI (FIX COLORE) --- */
    div.stButton > button:first-child {
        background-color: #D15627 !important; /* Arancione Ruggine */
        color: #FFFFFF !important; /* Testo BIANCO forzato */
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.2rem;
        font-family: 'Poppins', sans-serif;
        font-weight: 600;
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
    }
    
    div.stButton > button:first-child:hover {
        background-color: #B3441F !important; /* Arancione più scuro */
        color: #FFFFFF !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }

    /* --- KPI CARDS --- */
    [data-testid="stMetricValue"] {
        color: #066C9C !important; /* Numeri Blu */
        font-family: 'Poppins', sans-serif;
    }
    [data-testid="stMetricLabel"] {
        color: #54A1BF !important; /* Label azzurrine */
    }

    /* --- TITOLI REPORT --- */
    div.report-section h3 {
        color: #D15627 !important; /* Titoli sezioni Arancioni per stacco */
        border-bottom: 2px solid #D0E9F2;
        padding-bottom: 10px;
    }

    /* --- INFO BOX AI --- */
    .stAlert {
        background-color: #E6F4F9; /* Azzurro chiarissimo */
        border-left: 5px solid #066C9C;
        color: #2D3233;
    }

    /* --- STAMPA --- */
    @media print {
        /* 1. Nascondi elementi inutili di Streamlit */
        [data-testid="stSidebar"], 
        .stButton, 
        button, 
        header, 
        footer, 
        #MainMenu, 
        .stDeployButton,
        [data-testid="stToolbar"] {
            display: none !important;
        }

        /* 2. Reset Layout per foglio A4 bianco */
        .stApp, .block-container {
            background-color: white !important;
            margin: 0 !important;
            padding: 0 !important;
            max-width: 100vw !important;
        }

        /* 3. Gestione intelligente dei blocchi report */
        .report-section {
            page-break-inside: avoid; /* Evita di tagliare a metà i grafici */
            border: 1px solid #ddd;
            padding: 20px;
            margin-bottom: 20px;
            break-inside: avoid;
        }

        /* 4. Ottimizzazione Colori per risparmio inchiostro ma alta leggibilità */
        body {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            font-size: 12pt !important;
            color: black !important;
        }
        
        /* 5. Fix Dimensioni Grafici */
        canvas {
            max-width: 100% !important;
            height: auto !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 3. AI CONFIG ---
def configure_ai():
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
            return True
        return False
    except: return False

ai_configured = configure_ai()

def ask_gemini_advanced(df, report_name, kpi_curr, kpi_prev, comparison_active, business_context):
    if not ai_configured: return "⚠️ Chiave API AI mancante."
    
    data_preview = df.head(10).to_string(index=False)
    context_str = f"Settore: '{business_context}'." if business_context else "Generico."
    
    if comparison_active:
        kpi_text = ""
        for k, v in kpi_curr.items():
            prev = kpi_prev.get(k, 0)
            diff = v - prev
            perc = ((diff/prev)*100) if prev > 0 else 0
            kpi_text += f"- {k}: {v} (Var: {perc:.1f}%)\n"
        task = "Analizza CRESCITA/CALO e cause."
    else:
        kpi_text = ""
        for k, v in kpi_curr.items():
            kpi_text += f"- {k}: {v}\n"
        task = "Analizza DISTRIBUZIONE e Top Performer."

    prompt = f"""
    Sei un Analista Marketing (ADF Marketing). {context_str}
    Report: {report_name}
    KPI:
    {kpi_text}
    DATI:
    {data_preview}
    
    1. {task}
    2. Voto (1-10).
    3. Azione Consigliata.
    Sii sintetico.
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-lite-preview-09-2025')
        response = model.generate_content(prompt)
        return response.text
    except:
        try:
            model = genai.GenerativeModel('gemini-3-pro-preview')
            response = model.generate_content(prompt)
            return response.text
        except Exception as e: return f"⚠️ AI Error: {e}"

# --- 4. AUTH ---
def get_ga4_client():
    try:
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds_str = st.secrets["GOOGLE_CREDENTIALS"]
            try: creds_dict = json.loads(creds_str, strict=False)
            except json.JSONDecodeError:
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', creds_str) 
                clean_str = clean_str.replace('\n', '\\n')
                if not clean_str.startswith('{'): clean_str = creds_str.replace('\n', ' ')
                try: creds_dict = json.loads(clean_str, strict=False)
                except: return None
            return BetaAnalyticsDataClient(credentials=service_account.Credentials.from_service_account_info(creds_dict))
        elif os.path.exists('credentials.json'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
            return BetaAnalyticsDataClient()
        return None
    except: return None

# --- 5. DATA ENGINE ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active, retry=False):
    client = get_ga4_client()
    if not client: return "AUTH_ERROR", None, None

    metric_map = {"activeUsers": "Utenti", "sessions": "Sessioni", "screenPageViews": "Visualizzazioni", "conversions": "Conversioni", "eventCount": "Eventi", "totalRevenue": "Entrate (€)"}
    
    dims = [Dimension(name="date")]
    if report_kind == "Acquisizione Traffico": dims = [Dimension(name="sessionSourceMedium")]
    elif report_kind == "Campagne": dims = [Dimension(name="campaignName")]
    elif report_kind == "Panoramica Eventi": dims = [Dimension(name="eventName")]
    elif report_kind == "Pagine e Schermate": dims = [Dimension(name="pageTitle")]
    elif report_kind == "Landing Page": dims = [Dimension(name="landingPage")]
    elif report_kind == "Monetizzazione": dims = [Dimension(name="itemName")]
    elif report_kind == "Fidelizzazione": dims = [Dimension(name="newVsReturning")]
    elif report_kind == "Città": dims = [Dimension(name="city")]
    elif report_kind == "Dispositivi": dims = [Dimension(name="deviceCategory")]

    mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]
    if "Monetizzazione" in report_kind: mets = [Metric(name="itemsPurchased"), Metric(name="totalRevenue")]
    elif "Eventi" in report_kind: mets = [Metric(name="eventCount"), Metric(name="totalUsers")]
    elif "Campagne" in report_kind: mets = [Metric(name="sessions"), Metric(name="conversions")]

    try:
        req = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=start, end_date=end)], dimensions=dims, metrics=mets)
        res = client.run_report(req)
        data = []
        for row in res.rows:
            item = {'Dimensione': row.dimension_values[0].value}
            for i, m in enumerate(mets):
                ita = metric_map.get(m.name, m.name)
                item[ita] = float(row.metric_values[i].value)
            data.append(item)
        df = pd.DataFrame(data)
        
        curr, prev = {}, {}
        if not df.empty:
            for m in mets:
                ita = metric_map.get(m.name, m.name)
                curr[ita] = df[ita].sum()
            if comp_active:
                req_p = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=p_start, end_date=p_end)], dimensions=dims, metrics=mets)
                res_p = client.run_report(req_p)
                for m in mets: prev[metric_map.get(m.name, m.name)] = 0
                for row in res_p.rows:
                    for i, m in enumerate(mets):
                        prev[metric_map.get(m.name, m.name)] += float(row.metric_values[i].value)
        return "OK", df, (curr, prev)
    except Exception as e: return "API_ERROR", str(e), None

# --- 6. RENDERER ---
def render_chart_smart(df, report_kind):
    cols = [c for c in df.columns if c not in ['Dimensione', 'Data', 'date_obj']]
    if not cols: return
    main = cols[0]
    
    # Palette colori personalizzata (Blu Key, Arancio Key, etc)
    color_scale = alt.Scale(range=["#066C9C", "#D15627", "#54A1BF", "#2D3233"])
    
    if "Dispositivi" in report_kind or "Fidelizzazione" in report_kind:
        c = alt.Chart(df).mark_arc(innerRadius=60).encode(
            theta=alt.Theta(field=main, type="quantitative"),
            color=alt.Color(field="Dimensione", scale=color_scale),
            tooltip=["Dimensione", main]
        )
        st.altair_chart(c, use_container_width=True)
    elif "Panoramica" in report_kind and "Eventi" not in report_kind:
        st.line_chart(df, x='Data', y=cols)
    else:
        df_s = df.sort_values(by=main, ascending=False).head(15)
        c = alt.Chart(df_s).mark_bar().encode(
            x=alt.X(main, title=main),
            y=alt.Y('Dimensione', sort='-x', title=None),
            color=alt.value("#066C9C"),
            tooltip=['Dimensione', main]
        ).properties(height=350)
        st.altair_chart(c, use_container_width=True)

# --- 7. LOGIC ---
def generate_report(reports, pid, d1, d2, p1, p2, comp, context):
    res = {}
    bar = st.progress(0)
    for i, rep in enumerate(reports):
        status, df, kpi = get_ga4_data(pid, d1, d2, p1, p2, rep, comp)
        if status == "OK" and not df.empty:
            if rep == "Panoramica Trend":
                df['date_obj'] = pd.to_datetime(df['Dimensione'], format='%Y%m%d', errors='coerce')
                if not df['date_obj'].isnull().all():
                    df['Data'] = df['date_obj'].dt.strftime('%d/%m/%y')
                    df = df.sort_values(by='date_obj')
            comm = ask_gemini_advanced(df, rep, kpi[0], kpi[1], comp, context)
            res[rep] = {"df": df, "curr": kpi[0], "prev": kpi[1], "comm": comm}
        elif status == "AUTH_ERROR":
            st.error("Errore Autenticazione Cloud.")
            break
        bar.progress((i + 1) / len(reports))
    bar.empty()
    return res

# --- UI ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=100)
    
    st.markdown("### Configurazione Cliente")
    client_name = st.text_input("Cliente / Sito Web", placeholder="Es. Key4Sales.it")
    property_id = st.text_input("ID Proprietà (Numerico)", value=st.session_state.get('last_prop_id', ''))
    business_context = st.text_area("Settore / Contesto", placeholder="Es. E-commerce scarpe...", help="Aiuta l'IA")
    
    st.divider()
    date_opt = st.selectbox("Periodo", ("Ultimi 28 Giorni", "Ultimi 90 Giorni", "Ultimo Anno", "Personalizzato"))
    today = datetime.date.today()
    if date_opt == "Ultimi 28 Giorni": start_date = today - datetime.timedelta(days=28)
    elif date_opt == "Ultimi 90 Giorni": start_date = today - datetime.timedelta(days=90)
    elif date_opt == "Ultimo Anno": start_date = today - datetime.timedelta(days=365)
    else: start_date = st.date_input("Dal", today - datetime.timedelta(days=30))
    end_date = st.date_input("Al", today) if date_opt == "Personalizzato" else today
    
    comp_active = st.checkbox("Confronta periodo precedente", value=True)
    if comp_active:
        delta = end_date - start_date
        p_end = start_date - datetime.timedelta(days=1)
        p_start = p_end - delta
        st.caption(f"Vs: {p_start.strftime('%d/%m/%y')} - {p_end.strftime('%d/%m/%y')}")
    else: p_start, p_end = start_date, end_date # Dummy

    st.divider()
    grp = {
        "📊 Panoramica": ["Panoramica Trend"], "📥 Acquisizione": ["Acquisizione Traffico", "Campagne"],
        "👍 Coinvolgimento": ["Panoramica Eventi", "Pagine e Schermate", "Landing Page"],
        "💰 Monetizzazione": ["Monetizzazione"], "❤️ Fidelizzazione": ["Fidelizzazione"],
        "🌍 Utente": ["Città", "Dispositivi"]
    }
    sel_grp = st.selectbox("Sezione Report", ["REPORT COMPLETO"] + list(grp.keys()))
    target = [r for l in grp.values() for r in l] if sel_grp == "REPORT COMPLETO" else grp[sel_grp]
    
    st.write("")
    if st.button("🚀 GENERA REPORT"):
        st.session_state.last_prop_id = property_id
        if not property_id: st.error("Manca ID")
        else: st.session_state.report_data = generate_report(target, property_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d"), comp_active, business_context)

col1, col2 = st.columns([3, 1])
with col1:
    main_title = f"Report: {client_name}" if client_name else "Report Analitico GA4"
    st.title(main_title)
    st.caption(f"Analisi: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
with col2:
    st.write("")
    components.html("""<script>function printPage() { window.print(); }</script>
    <button onclick="printPage()" style="background-color:#D15627; color:white; border:none; padding:10px 20px; border-radius:5px; font-weight:bold; cursor:pointer; font-family:sans-serif;">🖨️ Stampa PDF</button>""", height=60)

if st.session_state.report_data:
    data = st.session_state.report_data
    for name, content in data.items():
        st.markdown('<div class="report-section">', unsafe_allow_html=True)
        st.markdown(f"### 📌 {name}")
        
        cur, pre = content['curr'], content['prev']
        cols = st.columns(len(cur))
        for idx, (k, v) in enumerate(cur.items()):
            if comp_active:
                pv = pre.get(k, 0)
                d = ((v - pv) / pv * 100) if pv > 0 else 0
                cols[idx].metric(k, f"{v:,.0f}".replace(",", ".") if isinstance(v, float) else v, f"{d:.1f}%")
            else: cols[idx].metric(k, f"{v:,.0f}".replace(",", ".") if isinstance(v, float) else v)
        
        st.info(f"🤖 **Analisi ADF:**\n\n{content['comm']}")
        render_chart_smart(content['df'], name)
        with st.expander(f"Dati: {name}"): st.dataframe(content['df'], use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

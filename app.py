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

# --- 2. DESIGN SYSTEM (PALETTE & FONT FIX) ---
st.markdown("""
<style>
    /* Importazione Font */
    @import url('https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Poppins:wght@600;700&display=swap');

    /* APPLICAZIONE PALETTE GLOBALE */
    /* Sfondo Generale */
    .stApp {
        background-color: #F7F7F7;
    }
    
    /* Testi Generali (Lato - Grigio Scuro Palette) */
    html, body, p, li, .stMarkdown {
        font-family: 'Lato', sans-serif !important;
        color: #2D3233 !important;
    }
    
    /* Titoli (Poppins - Nero/Grigio Scuro) */
    h1, h2, h3 {
        font-family: 'Poppins', sans-serif !important;
        color: #0D0D0D !important;
    }
    
    /* Titoli dei Report specifici (Blu Palette) */
    div.report-section h3 {
        color: #066C9C !important;
    }

    /* KPI Numerici (Blu Palette) */
    [data-testid="stMetricValue"] {
        font-family: 'Poppins', sans-serif;
        color: #066C9C !important;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Lato', sans-serif;
        color: #54A1BF !important; /* Variante chiara del blu */
    }

    /* Pulsante Primario (Arancione Ruggine Palette) */
    div.stButton > button:first-child {
        background-color: #D15627 !important; 
        color: white !important;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.6rem 1.2rem;
        font-family: 'Poppins', sans-serif;
    }
    div.stButton > button:first-child:hover {
        background-color: #B3441F !important;
        color: white !important;
    }

    /* Sidebar (Bianco/Grigio chiaro) */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #D0E9F2;
    }

    /* Box Info AI (Sfondo Azzurro chiaro Palette) */
    .stAlert {
        background-color: #D0E9F220; /* 20% opacità */
        border: 1px solid #066C9C;
    }

    /* Stile Stampa */
    @media print {
        [data-testid="stSidebar"] {display: none !important;}
        .stButton {display: none !important;}
        header {visibility: hidden !important;}
        footer {visibility: hidden !important;}
        .block-container {
            background-color: white !important;
            padding: 0px !important;
        }
        .report-section { 
            page-break-inside: avoid;
            padding-bottom: 20px;
            border-bottom: 2px solid #D0E9F2;
            margin-bottom: 20px;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 3. CONFIGURAZIONE AI ---
def configure_ai():
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
            return True
        else:
            return False
    except: return False

ai_configured = configure_ai()

def ask_gemini_advanced(df, report_name, kpi_curr, kpi_prev, comparison_active, business_context):
    if not ai_configured:
        return "⚠️ Chiave API AI mancante."
    
    data_preview = df.head(10).to_string(index=False)
    context_str = f"L'azienda opera nel settore: '{business_context}'." if business_context else "Settore non specificato."
    
    if comparison_active:
        kpi_text = ""
        for k, v in kpi_curr.items():
            prev = kpi_prev.get(k, 0)
            diff = v - prev
            perc = ((diff/prev)*100) if prev > 0 else 0
            kpi_text += f"- {k}: {v} (Var: {perc:.1f}%)\n"
        task_prompt = "1. Analizza la CRESCITA o il CALO (considerando stagionalità).\n2. Identifica cause probabili."
    else:
        kpi_text = ""
        for k, v in kpi_curr.items():
            kpi_text += f"- {k}: {v}\n"
        task_prompt = "1. Analizza la DISTRIBUZIONE attuale.\n2. Identifica i canali/prodotti migliori."

    prompt = f"""
    Sei un Senior Marketing Analyst italiano.
    CONTESTO CLIENTE: {context_str}
    Report: '{report_name}'.
    KPI:
    {kpi_text}
    DATI:
    {data_preview}
    COMPITI:
    {task_prompt}
    3. Assegna un VOTO Performance (1-10).
    4. Suggerisci 1 AZIONE PRATICA.
    OUTPUT: Markdown sintetico. No saluti.
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
        except Exception as e:
            return f"⚠️ AI non disponibile: {e}"

# --- 4. AUTH BLINDATA ---
def get_ga4_client():
    try:
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds_str = st.secrets["GOOGLE_CREDENTIALS"]
            try:
                creds_dict = json.loads(creds_str, strict=False)
            except json.JSONDecodeError:
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', creds_str) 
                clean_str = clean_str.replace('\n', '\\n') 
                if not clean_str.startswith('{'): 
                     clean_str = creds_str.replace('\n', ' ')
                try:
                     creds_dict = json.loads(creds_str.replace('\n', ' '), strict=False)
                except: return None

            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            return BetaAnalyticsDataClient(credentials=credentials)
        
        elif os.path.exists('credentials.json'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
            return BetaAnalyticsDataClient()
        else: return None
    except Exception as e:
        st.error(f"Errore Auth: {e}")
        return None

# --- 5. MOTORE DATI ---
def get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active):
    client = get_ga4_client()
    if not client: return "AUTH_ERROR", None, None

    metric_map = {
        "activeUsers": "Utenti", "sessions": "Sessioni", "screenPageViews": "Visualizzazioni",
        "conversions": "Conversioni", "eventCount": "Eventi", "totalRevenue": "Entrate (€)",
        "newUsers": "Nuovi Utenti"
    }

    dims = []
    mets = []
    
    if report_kind == "Acquisizione Traffico": dims = [Dimension(name="sessionSourceMedium")]
    elif report_kind == "Campagne": dims = [Dimension(name="campaignName")]
    elif report_kind == "Panoramica Eventi": dims = [Dimension(name="eventName")]
    elif report_kind == "Pagine e Schermate": dims = [Dimension(name="pageTitle")]
    elif report_kind == "Landing Page": dims = [Dimension(name="landingPage")]
    elif report_kind == "Monetizzazione": dims = [Dimension(name="itemName")]
    elif report_kind == "Fidelizzazione": dims = [Dimension(name="newVsReturning")]
    elif report_kind == "Città": dims = [Dimension(name="city")]
    elif report_kind == "Dispositivi": dims = [Dimension(name="deviceCategory")]
    else: dims = [Dimension(name="date")]

    if "Monetizzazione" in report_kind: mets = [Metric(name="itemsPurchased"), Metric(name="totalRevenue")]
    elif "Eventi" in report_kind: mets = [Metric(name="eventCount"), Metric(name="totalUsers")]
    elif "Campagne" in report_kind: mets = [Metric(name="sessions"), Metric(name="conversions")]
    else: mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]

    try:
        req_curr = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=start, end_date=end)], dimensions=dims, metrics=mets)
        res_curr = client.run_report(req_curr)

        data = []
        for row in res_curr.rows:
            item = {'Dimensione': row.dimension_values[0].value}
            for i, m in enumerate(mets):
                ita = metric_map.get(m.name, m.name)
                item[ita] = float(row.metric_values[i].value)
            data.append(item)
        df_curr = pd.DataFrame(data)

        kpi_curr = {}
        kpi_prev = {}
        
        if not df_curr.empty:
            for m in mets:
                ita = metric_map.get(m.name, m.name)
                kpi_curr[ita] = df_curr[ita].sum()
            
            if comp_active:
                req_prev = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=p_start, end_date=p_end)], dimensions=dims, metrics=mets)
                res_prev = client.run_report(req_prev)
                for m in mets:
                    ita = metric_map.get(m.name, m.name)
                    kpi_prev[ita] = 0
                for row in res_prev.rows:
                    for i, m in enumerate(mets):
                        ita = metric_map.get(m.name, m.name)
                        kpi_prev[ita] += float(row.metric_values[i].value)
        
        return "OK", df_curr, (kpi_curr, kpi_prev)

    except Exception as e:
        return "API_ERROR", str(e), None

# --- 6. RENDERER ---
def render_chart_smart(df, report_kind):
    numeric = [c for c in df.columns if c not in ['Dimensione', 'Data', 'date_obj']]
    if not numeric: return
    main_met = numeric[0]
    
    # Palette colori applicata ai grafici Altair
    if "Dispositivi" in report_kind or "Fidelizzazione" in report_kind:
        c = alt.Chart(df).mark_arc(innerRadius=50).encode(
            theta=alt.Theta(field=main_met, type="quantitative"),
            color=alt.Color(field="Dimensione", type="nominal", scale=alt.Scale(range=["#066C9C", "#D15627", "#D0E9F2", "#2D3233"])),
            tooltip=["Dimensione", main_met]
        )
        st.altair_chart(c, use_container_width=True)
    elif "Panoramica" in report_kind and "Eventi" not in report_kind: 
         st.line_chart(df, x='Data', y=numeric)
    else:
        df_s = df.sort_values(by=main_met, ascending=False).head(15)
        c = alt.Chart(df_s).mark_bar().encode(
            x=alt.X(main_met, title=main_met), 
            y=alt.Y('Dimensione', sort='-x', title=None),
            tooltip=['Dimensione', main_met],
            color=alt.value("#066C9C") # Blu Palette
        ).properties(height=350)
        st.altair_chart(c, use_container_width=True)

# --- 7. LOGICA ---
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
            st.error("Errore Autenticazione.")
            break
        bar.progress((i + 1) / len(reports))
    bar.empty()
    return res

# --- SIDEBAR ---
with st.sidebar:
    # LOGO RIDOTTO A 80PX COME RICHIESTO
    if os.path.exists("logo.png"): st.image("logo.png", width=80)
    
    st.markdown("### Configurazione Cliente")
    client_name = st.text_input("Nome Cliente / Sito Web", placeholder="Es. Key4Sales.it")
    property_id = st.text_input("ID Proprietà", value=st.session_state.get('last_prop_id', ''))
    business_context = st.text_area("Settore / Contesto", placeholder="Es. E-commerce...", help="Aiuta l'IA a dare consigli specifici")
    
    st.divider()
    
    date_opt = st.selectbox("Periodo", ("Ultimi 28 Giorni", "Ultimi 90 Giorni", "Ultimo Anno", "Personalizzato"))
    today = datetime.date.today()
    if date_opt == "Ultimi 28 Giorni": start_date = today - datetime.timedelta(days=28)
    elif date_opt == "Ultimi 90 Giorni": start_date = today - datetime.timedelta(days=90)
    elif date_opt == "Ultimo Anno": start_date = today - datetime.timedelta(days=365)
    else: start_date = st.date_input("Dal", today - datetime.timedelta(days=30))
    end_date = st.date_input("Al", today) if date_opt == "Personalizzato" else today
    
    comparison_active = st.checkbox("Confronta col periodo precedente", value=True)
    
    if comparison_active:
        delta = end_date - start_date
        p_end = start_date - datetime.timedelta(days=1)
        p_start = p_end - delta
        st.caption(f"Vs: {p_start.strftime('%d/%m/%y')} - {p_end.strftime('%d/%m/%y')}")
        s_s, s_e = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        p_s, p_e = p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d")
    else:
        s_s, s_e = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        p_s, p_e = s_s, s_e
        
    st.divider()
    
    grp = {
        "📊 Panoramica": ["Panoramica Trend"],
        "📥 Acquisizione": ["Acquisizione Traffico", "Campagne"],
        "👍 Coinvolgimento": ["Panoramica Eventi", "Pagine e Schermate", "Landing Page"],
        "💰 Monetizzazione": ["Monetizzazione"],
        "❤️ Fidelizzazione": ["Fidelizzazione"],
        "🌍 Utente": ["Città", "Dispositivi"]
    }
    sel_grp = st.selectbox("Sezione Report", ["REPORT COMPLETO"] + list(grp.keys()))
    target = [r for l in grp.values() for r in l] if sel_grp == "REPORT COMPLETO" else grp[sel_grp]
    
    st.write("")
    if st.button("🚀 GENERA REPORT"):
        st.session_state.last_prop_id = property_id
        if not property_id: st.error("Manca ID")
        else: st.session_state.report_data = generate_report(target, property_id, s_s, s_e, p_s, p_e, comparison_active, business_context)

# --- MAIN PAGE ---
col1, col2 = st.columns([3, 1])
with col1:
    main_title = f"Report Analitico GA4: {client_name}" if client_name else "Report Analitico GA4"
    st.title(main_title)
    st.caption(f"Analisi: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")

with col2:
    st.write("")
    components.html("""<script>function printPage() { window.print(); }</script>
    <button onclick="printPage()" style="background-color:#D15627; color:white; border:none; padding:10px 20px; border-radius:5px; font-weight:bold; cursor:pointer; font-family:sans-serif;">🖨️ Salva PDF</button>""", height=60)

if st.session_state.report_data:
    data = st.session_state.report_data
    for name, content in data.items():
        st.markdown('<div class="report-section">', unsafe_allow_html=True)
        st.markdown(f"### 📌 {name}")
        
        cur, pre = content['curr'], content['prev']
        cols = st.columns(len(cur))
        
        # --- FIX BUG: Sostituito 'val' con 'v' ---
        for idx, (k, v) in enumerate(cur.items()):
            if comparison_active:
                pv = pre.get(k, 0)
                d = ((v - pv) / pv * 100) if pv > 0 else 0
                cols[idx].metric(k, f"{v:,.0f}".replace(",", ".") if isinstance(v, float) else v, f"{d:.1f}%")
            else:
                cols[idx].metric(k, f"{v:,.0f}".replace(",", ".") if isinstance(v, float) else v)
        
        st.info(f"🤖 **Analisi ADF:**\n\n{content['comm']}")
        render_chart_smart(content['df'], name)
        
        with st.expander(f"Dati: {name}"):
            st.dataframe(content['df'], use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

elif st.session_state.get('last_prop_id'): pass
else: st.info("👈 Configura il cliente nella barra laterale e genera il report.")

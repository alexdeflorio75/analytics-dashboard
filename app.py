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
import time # Necessario per rallentare l'AI ed evitare errori

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="ADF Marketing Analyst", layout="wide", page_icon="📊")

query_params = st.query_params
default_id = query_params.get("id", "")
default_client = query_params.get("client", "")
default_context = query_params.get("context", "")

if 'report_data' not in st.session_state: st.session_state.report_data = None

# Funzione Logo
def get_base64_logo():
    if os.path.exists("logo.png"):
        with open("logo.png", "rb") as f: data = f.read()
        return base64.b64encode(data).decode()
    return ""
logo_b64 = get_base64_logo()

# --- 2. CSS STAMPA & DESIGN (FIX DEFINITIVO) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Poppins:wght@600;700&display=swap');
    
    .stApp { background-color: #F9F9F9; }
    html, body, p, div, label, .stMarkdown, .stRadio label { font-family: 'Lato', sans-serif !important; color: #2D3233 !important; }
    h1, h2, h3, h4 { font-family: 'Poppins', sans-serif !important; color: #0D0D0D !important; }
    
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important; border: 1px solid #066C9C !important; border-radius: 6px; font-size: 15px;
    }
    
    [data-testid="stSidebar"] .block-container { padding: 2rem 1.5rem; }
    
    /* Pulsante Rosso */
    div.stButton > button:first-child {
        background-color: #D15627 !important; color: white !important; border: none; font-weight: bold; padding: 0.8rem; width: 100%; margin-top: 10px;
    }
    div.stButton > button:first-child:hover { background-color: #A33B1B !important; }

    /* Report Layout */
    div.report-section h3 { color: #D15627 !important; border-bottom: 3px solid #D0E9F2; padding-bottom: 8px; margin-top: 30px; }
    [data-testid="stMetricValue"] { color: #066C9C !important; font-weight: 700; }

    /* --- STILE DI STAMPA "CHIURURGICO" --- */
    @media print {
        /* 1. Nascondi Barre e Pulsanti */
        [data-testid="stSidebar"], 
        header[data-testid="stHeader"], 
        .stDeployButton, 
        footer, 
        button, 
        .stButton {
            display: none !important;
        }

        /* 2. Resetta Margini per foglio A4 */
        .block-container {
            max-width: 100% !important;
            padding: 2rem !important;
            margin: 0 !important;
        }
        
        .stApp {
            background: white !important;
        }

        /* 3. Mostra Intestazione Stampa */
        #print-header {
            display: block !important;
            margin-bottom: 30px;
            border-bottom: 2px solid #D15627;
            padding-bottom: 15px;
        }

        /* 4. Gestione interruzioni pagina */
        .report-section { 
            page-break-inside: avoid;
            margin-bottom: 40px;
        }
        
        /* 5. Forza visualizzazione Grafici */
        canvas, .stVegaLiteChart {
            visibility: visible !important;
            max-width: 100% !important;
        }
    }
    
    #print-header { display: none; }
</style>
""", unsafe_allow_html=True)

# --- 3. AI (Con Ritardo per evitare errori) ---
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
    
    # RALLENTA per evitare errore 429 (Too Many Requests)
    time.sleep(2.5) 
    
    data_preview = df.head(10).to_string(index=False)
    ctx = f"Settore: {business_context}" if business_context else ""
    
    if comparison_active:
        kpi_text = ""
        for k, v in kpi_curr.items():
            prev = kpi_prev.get(k, 0)
            diff = v - prev
            perc = ((diff/prev)*100) if prev > 0 else 0
            kpi_text += f"- {k}: {v} (Var: {perc:.1f}%)\n"
        task = "Trend e cause."
    else:
        kpi_text = ""
        for k, v in kpi_curr.items(): kpi_text += f"- {k}: {v}\n"
        task = "Volumi attuali."

    prompt = f"""Analista Marketing. {ctx}. Report: {report_name}. KPI: {kpi_text}. DATI: {data_preview}. 1. {task} 2. Voto (1-10). 3. Consiglio. Sintetico. No saluti."""
    
    try:
        model = genai.GenerativeModel('gemini-3-pro-preview')
        return model.generate_content(prompt).text
    except:
        try:
            # Fallback su modello Lite
            model = genai.GenerativeModel('gemini-2.5-flash-lite-preview-09-2025')
            return model.generate_content(prompt).text
        except Exception as e: return f"⚠️ AI Error (Quota/Conn): {str(e)[:50]}..."

# --- 4. AUTH & DATA ---
def get_ga4_client():
    try:
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds_str = st.secrets["GOOGLE_CREDENTIALS"]
            clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', creds_str)
            clean_str = clean_str.replace('PRIVATE KEY-----', 'PRIVATE KEY-----\\n')
            if not clean_str.startswith('{'): clean_str = creds_str.replace('\n', ' ')
            creds_dict = json.loads(clean_str, strict=False)
            return BetaAnalyticsDataClient(credentials=service_account.Credentials.from_service_account_info(creds_dict))
        elif os.path.exists('credentials.json'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
            return BetaAnalyticsDataClient()
        return None
    except: return None

def get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active, retry=False):
    client = get_ga4_client()
    if not client: return "AUTH_ERROR", None, None

    metric_map = {"activeUsers": "Utenti", "sessions": "Sessioni", "screenPageViews": "Visualizzazioni", "conversions": "Conversioni", "eventCount": "Eventi", "totalRevenue": "Entrate (€)", "itemRevenue": "Entrate Prodotto (€)", "itemsPurchased": "Prodotti Venduti"}
    dims = [Dimension(name="date")]
    mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]

    if "Acquisizione" in report_kind: dims = [Dimension(name="sessionSourceMedium")]
    elif "Campagne" in report_kind: dims = [Dimension(name="campaignName")]; mets = [Metric(name="sessions"), Metric(name="conversions")]
    elif "Eventi" in report_kind: dims = [Dimension(name="eventName")]; mets = [Metric(name="eventCount"), Metric(name="totalUsers")]
    elif "Pagine" in report_kind: dims = [Dimension(name="pageTitle")]; mets = [Metric(name="screenPageViews"), Metric(name="activeUsers")]
    elif "Landing" in report_kind: dims = [Dimension(name="landingPage")]; mets = [Metric(name="sessions"), Metric(name="conversions")]
    elif "Fidelizzazione" in report_kind: dims = [Dimension(name="newVsReturning")]
    elif "Città" in report_kind: dims = [Dimension(name="city")]
    elif "Dispositivi" in report_kind: dims = [Dimension(name="deviceCategory")]
    elif "Monetizzazione" in report_kind:
        if not retry: dims = [Dimension(name="itemName")]; mets = [Metric(name="itemsPurchased"), Metric(name="itemRevenue")]
        else: dims = [Dimension(name="date")]; mets = [Metric(name="totalRevenue"), Metric(name="conversions")]

    try:
        req = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=start, end_date=end)], dimensions=dims, metrics=mets)
        res = client.run_report(req)
        data = []
        for row in res.rows:
            item = {'Dimensione': row.dimension_values[0].value}
            for i, m in enumerate(mets):
                ita = metric_map.get(m.name, m.name)
                val = row.metric_values[i].value
                item[ita] = float(val) if val else 0.0
            data.append(item)
        df = pd.DataFrame(data)
        curr, prev = {}, {}
        if not df.empty:
            for m in mets: curr[metric_map.get(m.name, m.name)] = df[metric_map.get(m.name, m.name)].sum()
            if comp_active:
                req_p = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=p_start, end_date=p_end)], dimensions=dims, metrics=mets)
                res_p = client.run_report(req_p)
                for m in mets: prev[metric_map.get(m.name, m.name)] = 0
                for row in res_p.rows:
                    for i, m in enumerate(mets): prev[metric_map.get(m.name, m.name)] += float(row.metric_values[i].value)
        return "OK", df, (curr, prev)
    except Exception as e:
        if "Monetizzazione" in report_kind and not retry: return get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active, True)
        return "API_ERROR", str(e), None

def render_chart_smart(df, report_kind):
    cols = [c for c in df.columns if c not in ['Dimensione', 'Data', 'date_obj']]
    if not cols: return
    main = cols[0]
    color_scale = alt.Scale(range=["#066C9C", "#D15627", "#54A1BF", "#2D3233"])
    if "Dispositivi" in report_kind or "Fidelizzazione" in report_kind:
        c = alt.Chart(df).mark_arc(innerRadius=60).encode(theta=alt.Theta(field=main, type="quantitative"), color=alt.Color(field="Dimensione", scale=color_scale), tooltip=["Dimensione", main])
        st.altair_chart(c, use_container_width=True)
    elif "Panoramica" in report_kind and "Eventi" not in report_kind and "Monetizzazione" not in report_kind: st.line_chart(df, x='Data', y=cols)
    else:
        df_s = df.sort_values(by=main, ascending=False).head(15)
        c = alt.Chart(df_s).mark_bar().encode(x=alt.X(main, title=main), y=alt.Y('Dimensione', sort='-x', title=None), color=alt.value("#066C9C"), tooltip=['Dimensione', main]).properties(height=350)
        st.altair_chart(c, use_container_width=True)

def generate_report(reports, pid, d1, d2, p1, p2, comp, context):
    res = {}
    bar = st.progress(0)
    for i, rep in enumerate(reports):
        status, df, kpi = get_ga4_data(pid, d1, d2, p1, p2, rep, comp)
        if status == "OK" and not df.empty:
            if rep == "Panoramica Trend":
                df['date_obj'] = pd.to_datetime(df['Dimensione'], format='%Y%m%d', errors='coerce')
                if not df['date_obj'].isnull().all():
                    df['Data'] = df['date_obj'].dt.strftime('%d/%m/%y'); df = df.sort_values(by='date_obj')
            comm = ask_gemini_advanced(df, rep, kpi[0], kpi[1], comp, context)
            res[rep] = {"df": df, "curr": kpi[0], "prev": kpi[1], "comm": comm, "error": None}
        elif status == "INCOMPATIBLE": res[rep] = {"error": "Dati non disponibili."}
        elif status == "AUTH_ERROR": st.error("Errore Autenticazione."); break
        elif status == "API_ERROR": res[rep] = {"error": f"Errore Tecnico: {df}"}
        bar.progress((i + 1) / len(reports))
    bar.empty()
    return res

# --- UI ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=80)
    st.markdown("### Configurazione")
    client_name = st.text_input("Cliente", value=default_client, placeholder="Nome Cliente")
    property_id = st.text_input("ID GA4", value=default_id if default_id else st.session_state.get('last_prop_id', ''))
    business_context = st.text_area("Contesto", value=default_context, placeholder="Settore...", height=80)
    st.markdown("---")
    date_opt = st.selectbox("Periodo", ("Ultimi 28 Giorni", "Ultimi 90 Giorni", "Ultimo Anno", "Personalizzato"))
    today = datetime.date.today()
    if date_opt == "Ultimi 28 Giorni": start_date = today - datetime.timedelta(days=28)
    elif date_opt == "Ultimi 90 Giorni": start_date = today - datetime.timedelta(days=90)
    elif date_opt == "Ultimo Anno": start_date = today - datetime.timedelta(days=365)
    else: start_date = st.date_input("Dal", today - datetime.timedelta(days=30))
    end_date = st.date_input("Al", today) if date_opt == "Personalizzato" else today
    comp_active = st.checkbox("Confronta periodo precedente", value=True)
    if comp_active:
        delta = end_date - start_date; p_end = start_date - datetime.timedelta(days=1); p_start = p_end - delta
        s_s, s_e = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"); p_s, p_e = p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d"); vs_text = f"{p_start.strftime('%d/%m/%y')} - {p_end.strftime('%d/%m/%y')}"
    else: s_s, s_e = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"); p_s, p_e = s_s, s_e; vs_text = ""

    grp = { "📊 Panoramica": ["Panoramica Trend"], "📥 Acquisizione": ["Acquisizione Traffico", "Campagne"], "👍 Coinvolgimento": ["Panoramica Eventi", "Pagine e Schermate", "Landing Page"], "💰 Monetizzazione": ["Monetizzazione"], "❤️ Fidelizzazione": ["Fidelizzazione"], "🌍 Utente": ["Città", "Dispositivi"] }
    sel_grp = st.selectbox("Visualizza", ["REPORT COMPLETO"] + list(grp.keys()))
    target = [r for l in grp.values() for r in l] if sel_grp == "REPORT COMPLETO" else grp[sel_grp]
    
    if st.button("🚀 GENERA REPORT"):
        st.session_state.last_prop_id = property_id
        if not property_id: st.error("Manca ID")
        else: st.session_state.report_data = generate_report(target, property_id, s_s, s_e, p_s, p_e, comp_active, business_context)

    with st.expander("🔗 Crea Link Condivisibile"):
        if property_id and client_name:
            safe_client = urllib.parse.quote(client_name); safe_ctx = urllib.parse.quote(business_context)
            final_domain = "https://adf-analytics.streamlit.app"
            st.code(f"{final_domain}/?id={property_id}&client={safe_client}&context={safe_ctx}", language="text")
        else: st.info("Compila i dati.")

# --- MAIN ---
if client_name:
    st.markdown(f"""
    <div id="print-header">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <img src="data:image/png;base64,{logo_b64}" width="120">
            <div style="text-align:right;">
                <h2 style="margin:0; color:#D15627;">ADF Marketing Report</h2>
                <p style="margin:0;"><b>Cliente:</b> {client_name}</p>
                <p style="margin:0;"><b>Periodo:</b> {start_date.strftime('%d/%m/%y')} - {end_date.strftime('%d/%m/%y')}</p>
                <p style="margin:0; font-size:12px; color:#666;">vs {vs_text}</p>
            </div>
        </div>
        <div style="margin-top:10px; padding:10px; background-color:#F0F8FF; border-radius:5px; font-size:13px;">
            <b>Contesto Analisi:</b> {business_context}
        </div>
    </div>
    """, unsafe_allow_html=True)

col1, col2 = st.columns([3, 1])
with col1:
    main_title = f"Report: {client_name}" if client_name else "Report Analitico GA4"
    st.title(main_title)
    st.caption(f"Analisi: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
with col2:
    st.write(""); components.html("""<script>function printPage() { window.print(); }</script><button onclick="printPage()" style="background-color:#D15627; color:white; border:none; padding:10px 20px; border-radius:5px; font-weight:bold; cursor:pointer; font-family:sans-serif;">🖨️ Salva PDF</button>""", height=60)

if st.session_state.report_data:
    data = st.session_state.report_data
    for name, content in data.items():
        st.markdown('<div class="report-section">', unsafe_allow_html=True)
        st.markdown(f"### 📌 {name}")
        if content.get("error"): st.warning(content["error"])
        else:
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

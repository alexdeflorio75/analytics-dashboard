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

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="ADF Marketing Analyst GA4", layout="wide", page_icon="📊")

if 'report_data' not in st.session_state:
    st.session_state.report_data = None
if 'report_type_generated' not in st.session_state:
    st.session_state.report_type_generated = None

# --- 2. CSS STAMPA ---
st.markdown("""
<style>
    div.stButton > button:first-child {
        background-color: #E03C31;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        border: none;
        padding: 0.5rem 1rem;
    }
    @media print {
        [data-testid="stSidebar"] {display: none !important;}
        .stButton {display: none !important;}
        header {visibility: hidden !important;}
        footer {visibility: hidden !important;}
        .block-container {
            background-color: white !important;
            color: black !important;
            max-width: 100% !important;
            padding: 0px !important;
            margin: 0px !important;
        }
        .report-section { 
            page-break-inside: avoid;
            padding-bottom: 20px;
            border-bottom: 1px solid #ddd;
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

def ask_gemini_advanced(df, report_name, kpi_curr, kpi_prev, comparison_active):
    if not ai_configured:
        return "⚠️ Chiave API AI mancante."
    
    data_preview = df.head(10).to_string(index=False)
    
    if comparison_active:
        kpi_text = ""
        for k, v in kpi_curr.items():
            prev = kpi_prev.get(k, 0)
            diff = v - prev
            perc = ((diff/prev)*100) if prev > 0 else 0
            kpi_text += f"- {k}: {v} (Var: {perc:.1f}%)\n"
        task_prompt = "1. Analizza CRESCITA/CALO rispetto al periodo precedente.\n2. Identifica la causa probabile."
    else:
        kpi_text = ""
        for k, v in kpi_curr.items():
            kpi_text += f"- {k}: {v}\n"
        task_prompt = "1. Analizza la DISTRIBUZIONE attuale.\n2. Identifica i top performer."

    prompt = f"""
    Sei un Senior Marketing Analyst italiano per ADF Marketing.
    Report: '{report_name}'.
    KPI:
    {kpi_text}
    DATI:
    {data_preview}
    COMPITI:
    {task_prompt}
    3. Assegna un VOTO (1-10).
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

# --- 4. FUNZIONE DI AUTENTICAZIONE SICURA (CLOUD) ---
def get_ga4_client():
    """Questa è la funzione magica che legge i Secrets dal Cloud"""
    try:
        # CASO 1: Siamo sul Cloud (Streamlit Share)
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds_json = st.secrets["GOOGLE_CREDENTIALS"]
            # Convertiamo la stringa JSON dei secrets in un dizionario
            creds_dict = json.loads(creds_json)
            # Creiamo le credenziali in memoria
            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            return BetaAnalyticsDataClient(credentials=credentials)
        
        # CASO 2: Siamo in Locale (PC)
        elif os.path.exists('credentials.json'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'
            return BetaAnalyticsDataClient()
            
        else:
            return None
    except Exception as e:
        st.error(f"Errore critico Auth: {e}")
        return None

# --- 5. MOTORE DATI ---
def get_ga4_data(prop_id, start, end, p_start, p_end, report_kind, comp_active):
    # USIAMO LA FUNZIONE SICURA QUI SOTTO
    client = get_ga4_client()
    
    if not client:
        return "MISSING_CREDENTIALS", None, None

    metric_map = {
        "activeUsers": "Utenti", "sessions": "Sessioni", "screenPageViews": "Visualizzazioni",
        "conversions": "Conversioni", "eventCount": "Eventi", "totalRevenue": "Entrate (€)",
        "newUsers": "Nuovi Utenti", "engagedSessions": "Sessioni con Interazione"
    }

    dims = []
    mets = []
    
    if report_kind == "Acquisizione Traffico":
        dims = [Dimension(name="sessionSourceMedium")]
        mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]
    elif report_kind == "Campagne":
        dims = [Dimension(name="campaignName")]
        mets = [Metric(name="sessions"), Metric(name="conversions")]
    elif report_kind == "Panoramica Eventi":
        dims = [Dimension(name="eventName")]
        mets = [Metric(name="eventCount"), Metric(name="totalUsers")]
    elif report_kind == "Pagine e Schermate":
        dims = [Dimension(name="pageTitle")]
        mets = [Metric(name="screenPageViews"), Metric(name="activeUsers")]
    elif report_kind == "Landing Page (Destinazione)":
        dims = [Dimension(name="landingPage")]
        mets = [Metric(name="sessions"), Metric(name="conversions")]
    elif report_kind == "Monetizzazione (E-commerce)":
        dims = [Dimension(name="itemName")]
        mets = [Metric(name="itemsPurchased"), Metric(name="totalRevenue")]
    elif report_kind == "Fidelizzazione (New vs Return)":
        dims = [Dimension(name="newVsReturning")]
        mets = [Metric(name="activeUsers"), Metric(name="sessions")]
    elif report_kind == "Dettagli Demografici (Città)":
        dims = [Dimension(name="city")]
        mets = [Metric(name="activeUsers")]
    elif report_kind == "Paese / Lingua":
        dims = [Dimension(name="country")]
        mets = [Metric(name="activeUsers")]
    elif report_kind == "Tecnologia (Dispositivi)":
        dims = [Dimension(name="deviceCategory")]
        mets = [Metric(name="activeUsers")]
    else:
        dims = [Dimension(name="date")]
        mets = [Metric(name="activeUsers"), Metric(name="sessions"), Metric(name="conversions")]

    try:
        req_curr = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=start, end_date=end)], dimensions=dims, metrics=mets)
        res_curr = client.run_report(req_curr)

        data = []
        for row in res_curr.rows:
            item = {'Dimensione': row.dimension_values[0].value}
            for i, m in enumerate(mets):
                ita_name = metric_map.get(m.name, m.name)
                item[ita_name] = float(row.metric_values[i].value)
            data.append(item)
        df_curr = pd.DataFrame(data)

        totals_curr = {}
        totals_prev = {}
        
        if not df_curr.empty:
            for m in mets:
                ita = metric_map.get(m.name, m.name)
                totals_curr[ita] = df_curr[ita].sum()
            
            if comp_active:
                req_prev = RunReportRequest(property=f"properties/{prop_id}", date_ranges=[DateRange(start_date=p_start, end_date=p_end)], dimensions=dims, metrics=mets)
                res_prev = client.run_report(req_prev)
                for m in mets:
                    ita = metric_map.get(m.name, m.name)
                    totals_prev[ita] = 0
                for row in res_prev.rows:
                    for i, m in enumerate(mets):
                        ita = metric_map.get(m.name, m.name)
                        totals_prev[ita] += float(row.metric_values[i].value)
        
        return "OK", df_curr, (totals_curr, totals_prev)

    except Exception as e:
        return "API_ERROR", str(e), None

# --- 6. RENDERER GRAFICI ---
def render_chart_smart(df, report_kind):
    numeric_cols = [c for c in df.columns if c not in ['Dimensione', 'Data', 'date_obj']]
    if not numeric_cols: return
    main_metric = numeric_cols[0]
    
    if "Tecnologia" in report_kind or "Fidelizzazione" in report_kind:
        chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
            theta=alt.Theta(field=main_metric, type="quantitative"),
            color=alt.Color(field="Dimensione", type="nominal"),
            tooltip=["Dimensione", main_metric]
        )
        st.altair_chart(chart, use_container_width=True)
    elif "Panoramica" in report_kind and "Eventi" not in report_kind: 
         st.line_chart(df, x='Data', y=numeric_cols)
    else:
        df_sorted = df.sort_values(by=main_metric, ascending=False).head(15)
        chart = alt.Chart(df_sorted).mark_bar().encode(
            x=alt.X(main_metric, title=main_metric), 
            y=alt.Y('Dimensione', sort='-x', title=None),
            tooltip=['Dimensione', main_metric]
        ).properties(height=350)
        st.altair_chart(chart, use_container_width=True)

# --- 7. LOGICA GENERAZIONE ---
def generate_report_logic(reports, prop_id, d_start, d_end, p_start, p_end, comp_active):
    results = {}
    progress_bar = st.progress(0)
    
    for idx, rep_name in enumerate(reports):
        status, df, kpi = get_ga4_data(prop_id, d_start, d_end, p_start, p_end, rep_name, comp_active)
        
        if status == "OK" and not df.empty:
            if rep_name == "Panoramica Trend":
                 df['date_obj'] = pd.to_datetime(df['Dimensione'], format='%Y%m%d', errors='coerce')
                 if not df['date_obj'].isnull().all():
                     df['Data'] = df['date_obj'].dt.strftime('%d/%m/%y')
                     df = df.sort_values(by='date_obj')

            comment = ask_gemini_advanced(df, rep_name, kpi[0], kpi[1], comp_active)
            results[rep_name] = {"df": df, "kpi_curr": kpi[0], "kpi_prev": kpi[1], "comment": comment}
        
        elif status == "MISSING_CREDENTIALS":
            st.error("ERRORE CREDENZIALI: Controlla Secrets su Streamlit Cloud.")
            break
        elif status == "API_ERROR":
             st.error(f"Errore API Google: {df}")
             break
            
        progress_bar.progress((idx + 1) / len(reports))
    
    progress_bar.empty()
    return results

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=80)
    
    st.header("ADF Marketing Analyst")
    property_id = st.text_input("ID Proprietà", value=st.session_state.get('last_prop_id', ''))
    
    st.divider()
    
    date_opt = st.selectbox("Intervallo", ("Ultimi 28 Giorni", "Ultimi 90 Giorni", "Ultimo Anno", "Personalizzato"))
    today = datetime.date.today()
    
    if date_opt == "Ultimi 28 Giorni": start_date = today - datetime.timedelta(days=28)
    elif date_opt == "Ultimi 90 Giorni": start_date = today - datetime.timedelta(days=90)
    elif date_opt == "Ultimo Anno": start_date = today - datetime.timedelta(days=365)
    else: start_date = st.date_input("Dal", today - datetime.timedelta(days=30))
    end_date = st.date_input("Al", today) if date_opt == "Personalizzato" else today
    
    comparison_active = st.checkbox("✅ Confronta col periodo precedente", value=True)
    
    if comparison_active:
        delta = end_date - start_date
        prev_end = start_date - datetime.timedelta(days=1)
        prev_start = prev_end - delta
        st.caption(f"Vs: {prev_start.strftime('%d/%m/%y')} - {prev_end.strftime('%d/%m/%y')}")
        s_str, e_str = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        ps_str, pe_str = prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")
    else:
        s_str, e_str = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        ps_str, pe_str = s_str, e_str 
        
    st.divider()
    
    report_groups = {
        "📊 Panoramica": ["Panoramica Trend"],
        "📥 Acquisizione": ["Acquisizione Traffico", "Campagne"],
        "👍 Coinvolgimento": ["Panoramica Eventi", "Pagine e Schermate", "Landing Page (Destinazione)"],
        "💰 Monetizzazione": ["Monetizzazione (E-commerce)"],
        "❤️ Fidelizzazione": ["Fidelizzazione (New vs Return)"],
        "🌍 Utente": ["Dettagli Demografici (Città)", "Paese / Lingua", "Tecnologia (Dispositivi)"]
    }
    
    selected_group = st.selectbox("Categoria Report", ["REPORT COMPLETO (Tutto)"] + list(report_groups.keys()))
    
    if selected_group == "REPORT COMPLETO (Tutto)":
        target_reports = [r for sublist in report_groups.values() for r in sublist]
    else:
        target_reports = report_groups[selected_group]
    
    st.markdown("---")
    if st.button("🚀 GENERA REPORT", type="primary"):
        st.session_state.last_prop_id = property_id
        if not property_id:
            st.error("Manca ID Proprietà")
        else:
            st.session_state.report_data = generate_report_logic(target_reports, property_id, s_str, e_str, ps_str, pe_str, comparison_active)

# --- MAIN PAGE ---
c1, c2 = st.columns([3, 1])
with c1:
    st.title("📊 Report Analitico GA4")
    st.markdown(f"Analisi: **{start_date.strftime('%d/%m/%Y')}** - **{end_date.strftime('%d/%m/%Y')}**")
with c2:
    st.write("")
    components.html("""<script>function printPage() { window.print(); }</script>
    <button onclick="printPage()" style="background-color:#E03C31; color:white; border:none; padding:10px 20px; border-radius:5px; font-weight:bold; cursor:pointer;">🖨️ Stampa Report</button>""", height=60)

if st.session_state.report_data:
    data_store = st.session_state.report_data
    
    for rep_name, content in data_store.items():
        st.markdown('<div class="report-section">', unsafe_allow_html=True)
        st.markdown(f"### 📌 {rep_name}")
        
        curr, prev = content['kpi_curr'], content['kpi_prev']
        cols = st.columns(len(curr))
        for idx, (key, val) in enumerate(curr.items()):
            if comparison_active:
                p_val = prev.get(key, 0)
                delta_val = ((val - p_val) / p_val * 100) if p_val > 0 else 0
                cols[idx].metric(key, f"{val:,.0f}".replace(",", "."), f"{delta_val:.1f}%")
            else:
                cols[idx].metric(key, f"{val:,.0f}".replace(",", "."))
        
        st.write("")
        st.info(f"🤖 **Analisi ADF:**\n\n{content['comment']}")
        render_chart_smart(content['df'], rep_name)
        
        with st.expander(f"Dati: {rep_name}"):
            st.dataframe(content['df'], use_container_width=True, hide_index=True)
            
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

elif st.session_state.get('last_prop_id'):
    pass
else:
    st.info("👈 Seleziona i parametri e clicca GENERA REPORT.")

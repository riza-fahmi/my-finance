import streamlit as st
import pandas as pd
import fitz
import json
import google.generativeai as genai
from st_supabase_connection import SupabaseConnection

# --- 1. SECURITY CHECK ---
def check_password():
    def password_entered():
        # Membaca password dari secrets.toml (local) atau Secrets Cloud
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Access Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Access Password", type="password", on_change=password_entered, key="password")
        st.error("Password salah.")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="FIN-CORE AI VAULT", layout="wide")

# Setup Gemini & Supabase dari Secrets
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-flash-latest')
conn = st.connection("supabase", type=SupabaseConnection)

CATEGORIES = ["Income", "Food & Beverage", "Shopping", "Bills & Topup", "Transportation", "Paylater & Debt", "Housing", "Others"]

# --- 3. AI CORE FUNCTIONS ---
def ai_parse_text(raw_text):
    prompt = f"""
    Tugas: Ekstrak data mutasi BCA ke JSON array.
    Kategori: {CATEGORIES}
    Rules: Food (Warteg, Batagor, Cafe), Transport (Grab, Gojek, BBM), Shopping (Shopee, Tokped). 
    Wajib isi Kategori, jangan kosong!
    Format: [{{ "Date": "DD/MM", "Description": "...", "Amount": float, "Type": "Income/Expense", "Category": "..." }}]
    Teks: {raw_text}
    """
    response = model.generate_content(prompt)
    clean_json = response.text.replace('```json', '').replace('```', '').strip()
    return json.loads(clean_json)

def ai_analyze_spending(current_list, history_text=None):
    prompt = f"""
    Analisa spending ini: {current_list}
    History: {history_text if history_text else 'Baru pertama kali.'}
    Kasih analisa singkat & santai soal kebocoran dana dan saran finansial.
    """
    response = model.generate_content(prompt)
    return response.text

# --- 4. SESSION STATE ---
if "df" not in st.session_state: st.session_state.df = None
if "analysis" not in st.session_state: st.session_state.analysis = ""

# --- 5. SIDEBAR ---
with st.sidebar:
    st.title("🏦 VAULT v34.0")
    file = st.file_uploader("Upload Mutasi (PDF)", type="pdf")
    if file and st.button("🚀 Run AI Audit"):
        with st.spinner("AI Processing..."):
            doc = fitz.open(stream=file.read(), filetype="pdf")
            raw_text = "\n".join([page.get_text() for page in doc])
            
            parsed_data = ai_parse_text(raw_text)
            st.session_state.df = pd.DataFrame(parsed_data)
            
            # Ambil history terakhir dari Supabase
            res = conn.table("vault_finance").select("analysis").order("id", desc=True).limit(1).execute()
            past_msg = res.data[0]['analysis'] if res.data else None
            st.session_state.analysis = ai_analyze_spending(parsed_data, past_msg)

# --- 6. MAIN UI ---
tab1, tab2 = st.tabs(["📊 ANALYSIS & DASHBOARD", "🗄️ VAULT RECORDS"])

with tab1:
    if st.session_state.df is not None:
        df = st.session_state.df
        st.info(st.session_state.analysis)
        
        # Dashboard
        t_in = df[df['Type'] == 'Income']['Amount'].sum()
        t_out = df[df['Type'] == 'Expense']['Amount'].sum()
        m1, m2, m3 = st.columns(3)
        m1.metric("Inflow", f"Rp {t_in:,.0f}")
        m2.metric("Outflow", f"Rp {t_out:,.0f}", delta=f"-{t_out:,.0f}", delta_color="inverse")
        m3.metric("Net", f"Rp {t_in - t_out:,.0f}")
        
        st.bar_chart(df[df['Type'] == 'Expense'].groupby('Category')['Amount'].sum())

        # Review Table
        st.session_state.df = st.data_editor(df, use_container_width=True, hide_index=True)
        
        if st.button("💾 Commit to Supabase Cloud", use_container_width=True):
            month_label = f"Periode_{st.session_state.df['Date'].iloc[0].split('/')[-1]}"
            # Simpan ke Supabase
            entry = {
                "periode": month_label,
                "data": st.session_state.df.to_dict('records'),
                "analysis": st.session_state.analysis
            }
            conn.table("vault_finance").insert(entry).execute()
            st.success("Data permanen di Cloud!")
            st.balloons()
            st.session_state.df = None
            st.rerun()
    else:
        st.info("Silakan upload PDF.")

with tab2:
    # Ambil semua data dari Supabase
    res = conn.table("vault_finance").select("*").order("id", desc=True).execute()
    if res.data:
        for row in res.data:
            with st.expander(f"📂 {row['periode']}"):
                st.write(row['analysis'])
                st.dataframe(pd.DataFrame(row['data']), use_container_width=True)
                if st.button("🗑️ Delete", key=f"del_{row['id']}"):
                    conn.table("vault_finance").delete().eq("id", row['id']).execute()
                    st.rerun()
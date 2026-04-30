import streamlit as st
import pandas as pd
import fitz
import json
import google.generativeai as genai
from st_supabase_connection import SupabaseConnection

# --- 1. DYNAMIC SECURITY ---
# Sekarang password lo = User Key. Beda password, beda isi Vault!
# --- 1. DYNAMIC & COMPACT SECURITY ---
def check_password():
    # 1. CEK MASTER PASSWORD (Biar orang asing gak bisa sembarang masuk)
    if "authenticated" not in st.session_state:
        empty1, col_login, empty2 = st.columns([1, 1, 1])
        with col_login:
            st.markdown("### 🛡️ FIN-CORE Access")
            with st.container(border=True):
                master_pwd = st.text_input("Master Access Code", type="password")
                if st.button("Masuk Aplikasi", use_container_width=True):
                    # Cek ke secrets.toml atau Secrets Cloud
                    if master_pwd == st.secrets["APP_PASSWORD"]:
                        st.session_state["authenticated"] = True
                        st.rerun()
                    else:
                        st.error("Access Code Salah!")
        return False

    # 2. CEK VAULT KEY (Multi-User Space)
    if "user_key" not in st.session_state:
        empty1, col_login, empty2 = st.columns([1, 1, 1])
        with col_login:
            st.markdown("### 🔐 Pilih Vault Anda")
            with st.container(border=True):
                pwd = st.text_input("Vault Key (Bebas/User)", type="password", placeholder="Contoh: riza123 atau tamu777")
                if st.button("Buka Vault", use_container_width=True):
                    st.session_state["user_key"] = pwd
                    st.rerun()
            st.caption("Gunakan key yang sama untuk melihat history Anda kembali.")
        return False
    
    return True

if not check_password():
    st.stop()

# --- 2. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="FIN-CORE AI", layout="wide")
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-flash-latest')
conn = st.connection("supabase", type=SupabaseConnection)

user_key = st.session_state["user_key"]
CATEGORIES = ["Income", "Food & Beverage", "Shopping", "Bills & Topup", "Transportation", "Paylater & Debt", "Housing", "Others"]

# --- 3. AI CORE WITH LEARNING ---
def ai_parse_text(raw_text):
    # Ambil "contekan" dari database biar AI belajar
    rules = conn.table("ai_learning").select("description, correct_category").eq("user_key", user_key).execute()
    learning_context = ""
    if rules.data:
        learning_context = "PENTING! User mau kategori ini khusus: " + ", ".join([f"{r['description']} -> {r['correct_category']}" for r in rules.data])

    prompt = f"""
    Tugas: Ekstrak mutasi ke JSON.
    Context Belajar: {learning_context}
    Kategori Wajib: {CATEGORIES}
    Format: [{{ "Date": "DD/MM", "Description": "...", "Amount": float, "Type": "Income/Expense", "Category": "..." }}]
    Teks: {raw_text}
    """
    response = model.generate_content(prompt)
    return json.loads(response.text.replace('```json', '').replace('```', '').strip())

def ai_analyze_spending(current_list):
    prompt = f"""
    Analisa data ini: {current_list}
    Berikan:
    1. SKOR_KESEHATAN: (Angka 1-10)
    2. ANALISA: (Analisa singkat ala IT Auditor santai)
    3. SARAN: (1 saran konkret)
    """
    response = model.generate_content(prompt)
    return response.text

# --- 4. SIDEBAR ---
with st.sidebar:
    st.title("🏦 VAULT MENU")
    # Tampilkan key yang sedang aktif (disensor dikit biar keren)
    current_key = st.session_state['user_key']
    st.write(f"Logged in as: `{current_key[:3]}***` ✨")
    
    if st.button("🚪 Logout Total", use_container_width=True):
            del st.session_state["authenticated"]
            del st.session_state["user_key"]
        st.rerun()
    st.divider()
        
    file = st.file_uploader("Upload Mutasi", type="pdf")
    if file and st.button("🚀 Run AI Audit"):
        with st.spinner("AI lagi nge-grade keuangan lo..."):
            doc = fitz.open(stream=file.read(), filetype="pdf")
            raw_text = "\n".join([page.get_text() for page in doc])
            st.session_state.df = pd.DataFrame(ai_parse_text(raw_text))
            st.session_state.analysis = ai_analyze_spending(st.session_state.df.to_dict('records'))

# --- 5. MAIN UI ---
tab1, tab2 = st.tabs(["📊 DASHBOARD", "🗄️ RECORDS"])

with tab1:
    if st.session_state.get("df") is not None:
        # Tampilan Skor ala Dashboard Pro
        col1, col2 = st.columns([1, 3])
        with col1:
            # Sederhana aja buat dapetin angka skor dari teks AI
            score = "N/A"
            for line in st.session_state.analysis.split('\n'):
                if "SKOR_KESEHATAN" in line: score = line.split(':')[-1].strip()
            st.metric("Financial Health Score", f"⭐ {score}/10")
        
        with col2:
            st.info(st.session_state.analysis)

        # Dashboard Visual
        st.bar_chart(st.session_state.df[st.session_state.df['Type'] == 'Expense'].groupby('Category')['Amount'].sum())

        st.subheader("📝 Transaction Review")
        st.caption("Tips: Ganti kategori yang salah, lalu klik 'Save' di bawah agar AI belajar.")
        
        # Editor
        edited_df = st.data_editor(st.session_state.df, use_container_width=True, hide_index=True)
        
        if st.button("💾 Save to Vault & Train AI", use_container_width=True):
            # Cek mana yang berubah kategorinya buat dimasukin ke tabel belajar
            for i, row in edited_df.iterrows():
                old_cat = st.session_state.df.iloc[i]['Category']
                if row['Category'] != old_cat:
                    conn.table("ai_learning").insert({
                        "user_key": user_key,
                        "description": row['Description'],
                        "correct_category": row['Category']
                    }).execute()
            
            # Simpan data utama
            entry = {
                "user_key": user_key,
                "periode": f"Periode_{edited_df['Date'].iloc[0]}",
                "data": edited_df.to_dict('records'),
                "analysis": st.session_state.analysis
            }
            conn.table("vault_finance").insert(entry).execute()
            st.success("Data Disimpan & AI makin pinter!")
            st.session_state.df = None
            st.rerun()
    else:
        st.write("Silakan upload PDF.")

with tab2:
    # Filter data HANYA milik user_key ini
    res = conn.table("vault_finance").select("*").eq("user_key", user_key).order("id", desc=True).execute()
    for row in res.data:
        with st.expander(f"📂 {row['periode']}"):
            st.write(row['analysis'])
            st.dataframe(pd.DataFrame(row['data']), use_container_width=True)

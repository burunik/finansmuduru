
import os
import json
import sqlite3
from datetime import date, datetime
from io import StringIO

import pandas as pd
import streamlit as st

# ---------------------------
# App Config
# ---------------------------
st.set_page_config(page_title="Mini Fiyat Analizcisi Pro", page_icon="🧮", layout="wide")
st.title("🧮 Mini Fiyat Analizcisi Pro")
st.caption("Tarih bazlı maliyet takibi, aylık kâr/zarar raporu ve **Now** vs **What‑If** senaryoları")

DB_PATH = "/mnt/data/mini_fiyat.db"

# ---------------------------
# DB Helpers
# ---------------------------
def get_conn():
    os.makedirs("/mnt/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date TEXT,
            year_month TEXT,
            scenario TEXT,
            product_name TEXT,
            batch_size INTEGER,
            materials_json TEXT,
            labor_hours REAL,
            hourly_rate REAL,
            monthly_rent REAL,
            monthly_util REAL,
            other_fixed REAL,
            employee_count INTEGER,
            avg_salary REAL,
            monthly_total_production INTEGER,
            target_margin_pct REAL,
            actual_price REAL,
            materials_total REAL,
            labor_total REAL,
            fixed_total_for_batch REAL,
            total_cost REAL,
            unit_cost REAL,
            recommended_price REAL,
            revenue REAL,
            profit REAL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_record(payload: dict):
    conn = get_conn()
    cur = conn.cursor()
    cols = ",".join(payload.keys())
    qmarks = ",".join(["?"] * len(payload))
    cur.execute(f"INSERT INTO records ({cols}) VALUES ({qmarks})", list(payload.values()))
    conn.commit()
    conn.close()

def load_month(year_month: str):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM records WHERE year_month = ? ORDER BY record_date DESC, id DESC",
                           conn, params=(year_month,))
    conn.close()
    return df

def load_all(limit=500):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM records ORDER BY record_date DESC, id DESC LIMIT ?", conn, params=(limit,))
    conn.close()
    return df

init_db()

# ---------------------------
# Utilities
# ---------------------------
def calc_finance(materials_df: pd.DataFrame, labor_hours: float, hourly_rate: float,
                 monthly_rent: float, monthly_util: float, other_fixed: float,
                 employee_count: int, avg_salary: float, monthly_total_production: int,
                 batch_size: int, target_margin_pct: float, actual_price: float | None):
    # Materials
    df = materials_df.copy()
    if len(df.columns) == 0:
        df = pd.DataFrame(columns=["Malzeme","Miktar","Birim","Birim Fiyatı (₺)"])
    if "Tutar (₺)" not in df.columns:
        df["Tutar (₺)"] = 0.0
    df["Tutar (₺)"] = df.get("Miktar", 0).fillna(0) * df.get("Birim Fiyatı (₺)", 0).fillna(0)
    materials_total = float(df["Tutar (₺)"].sum())

    # Labor
    labor_total = float(labor_hours * hourly_rate)

    # Fixed allocation
    payroll = float(employee_count * avg_salary)
    fixed_total_monthly = float(monthly_rent + monthly_util + other_fixed + payroll)
    fixed_cost_per_unit_allocation = fixed_total_monthly / max(monthly_total_production, 1)
    fixed_total_for_batch = fixed_cost_per_unit_allocation * batch_size

    total_cost = materials_total + labor_total + fixed_total_for_batch
    unit_cost = total_cost / max(batch_size, 1)

    target_margin = target_margin_pct / 100.0
    recommended_price = unit_cost * (1 + target_margin)

    revenue_now = None
    profit_now = None
    if actual_price is not None and actual_price > 0:
        revenue_now = actual_price * batch_size
        profit_now = revenue_now - total_cost

    return {
        "materials_total": round(materials_total, 2),
        "labor_total": round(labor_total, 2),
        "fixed_total_for_batch": round(fixed_total_for_batch, 2),
        "total_cost": round(total_cost, 2),
        "unit_cost": round(unit_cost, 2),
        "recommended_price": round(recommended_price, 2),
        "revenue_now": None if revenue_now is None else round(revenue_now, 2),
        "profit_now": None if profit_now is None else round(profit_now, 2),
        "fixed_cost_per_unit": round(fixed_cost_per_unit_allocation, 2)
    }

def ym_from_date(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

# ---------------------------
# Sidebar: Navigation & Settings
# ---------------------------
st.sidebar.header("📍 Gezinti")
page = st.sidebar.radio("Sayfa", ["Now (Gerçek durum)", "What‑If (Senaryo)", "Geçmiş & Raporlar", "Yardım"])

st.sidebar.markdown("---")
st.sidebar.header("⚙️ AI Yorumu (opsiyonel)")
use_ai = st.sidebar.checkbox("AI yorumu üret")
provider = st.sidebar.selectbox("Sağlayıcı", ["Groq (ücretsiz)", "OpenAI"], index=0)
if provider == "Groq (ücretsiz)":
    ai_base = "https://api.groq.com/openai/v1"
    ai_model = st.sidebar.selectbox("Model", ["llama-3.1-8b-instant"], index=0)
    api_key_label = "GROQ_API_KEY"
else:
    ai_base = "https://api.openai.com/v1"
    ai_model = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-4o"], index=0)
    api_key_label = "OPENAI_API_KEY"
api_key = st.sidebar.text_input(api_key_label, type="password", help="Anahtarını buraya gir.")

st.sidebar.markdown("---")
st.sidebar.caption("💡 İpucu: **Now** gerçek verileri, **What‑If** simülasyonları ayrı ayrı kaydeder.")

# ---------------------------
# Shared Inputs
# ---------------------------
def materials_editor(default_rows=None, key="materials"):
    if default_rows is None:
        default_rows = [
            {"Malzeme": "Zeytinyağı", "Miktar": 200.0, "Birim": "g", "Birim Fiyatı (₺)": 0.12},
            {"Malzeme": "Lavanta Yağı", "Miktar": 10.0, "Birim": "ml", "Birim Fiyatı (₺)": 1.50},
            {"Malzeme": "Ambalaj", "Miktar": 1.0, "Birim": "adet", "Birim Fiyatı (₺)": 5.00},
        ]
    df = st.data_editor(pd.DataFrame(default_rows), num_rows="dynamic", use_container_width=True, key=key)
    return df

def ai_commentary(prompt: str):
    from openai import OpenAI
    try:
        if not api_key:
            return ""
        client = OpenAI(api_key=api_key, base_url=ai_base)
        resp = client.chat.completions.create(
            model=ai_model,
            messages=[
                {"role": "system", "content": "You are a concise Turkish business assistant for small makers. Keep it to 3-5 sentences."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=220
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"AI yorumu alınamadı: {e}")
        return ""

def build_prompt(product_name, batch_size, target_margin_pct, actual_price,
                 calc, note=""):
    return f"""
Aşağıdaki maliyet analizi için Türkçe, 3-5 cümle ile kısa ve net bir yorum yaz.
- En yüksek maliyet kalemini belirt.
- Kısa bir iyileştirme önerisi yap (ör. batch büyütmek, birim fiyat pazarlığı).
- Hedef kâra göre satış fiyatı mantıklı mı değerlendir.

Ürün: {product_name}
Batch: {batch_size} adet
Birim maliyet: {calc['unit_cost']:.2f} ₺
Önerilen satış fiyatı (%{int(target_margin_pct)} kâr): {calc['recommended_price']:.2f} ₺
Gerçek satış fiyatı: {('—' if actual_price in (None, 0) else f'{actual_price:.2f} ₺')}
Hammadde: {calc['materials_total']} ₺
İşçilik: {calc['labor_total']} ₺
Sabit gider (batch payı): {calc['fixed_total_for_batch']} ₺
Toplam: {calc['total_cost']} ₺
Not: {note}
""".strip()

# ---------------------------
# Page: NOW
# ---------------------------
if page == "Now (Gerçek durum)":
    st.header("Now — Gerçek Üretim ve Satış")
    st.write("**Now**: Gerçek maliyetleri ve **fiili satış fiyatını** girersin; kâr/zararı hesaplar ve tarih ile kaydeder.")

    col_top = st.columns(4)
    with col_top[0]:
        product_name = st.text_input("Ürün adı", value="Lavanta Sabunu")
    with col_top[1]:
        record_date = st.date_input("Tarih", value=date.today())
    with col_top[2]:
        batch_size = st.number_input("Bu üretimdeki adet (batch size)", min_value=1, value=10, step=1)
    with col_top[3]:
        actual_price = st.number_input("Gerçek satış fiyatı (₺/adet)", min_value=0.0, value=70.0, step=1.0)

    st.markdown("### 🧴 Malzeme Giderleri")
    materials_df = materials_editor(key="mat_now")

    st.markdown("### 🧍‍♀️ İşçilik Giderleri")
    c1, c2 = st.columns(2)
    with c1:
        labor_hours = st.number_input("Toplam üretim süresi (saat)", min_value=0.0, value=1.0, step=0.5, key="labor_hours_now")
    with c2:
        hourly_rate = st.number_input("Saatlik ücret (₺/saat)", min_value=0.0, value=200.0, step=10.0, key="hourly_rate_now")

    st.markdown("### 🏭 Sabit Giderler (Aylık)")
    f1, f2 = st.columns(2)
    with f1:
        monthly_rent = st.number_input("Kira (₺/ay)", min_value=0.0, value=5000.0, step=100.0, key="rent_now")
        monthly_util = st.number_input("Elektrik/Su/Doğalgaz (₺/ay)", min_value=0.0, value=800.0, step=50.0, key="util_now")
        other_fixed = st.number_input("Diğer sabit giderler (₺/ay)", min_value=0.0, value=200.0, step=50.0, key="other_now")
    with f2:
        employee_count = st.number_input("Çalışan sayısı", min_value=0, value=0, step=1, key="emp_now")
        avg_salary = st.number_input("Ortalama maaş (₺/çalışan/ay)", min_value=0.0, value=0.0, step=100.0, key="sal_now")
        monthly_total_production = st.number_input("Aylık toplam üretim adedi (tüm ürünler)", min_value=1, value=500, step=10, key="prod_now")

    st.markdown("### 🎯 Hedef Kâr (karşılaştırma için)")
    target_margin_pct = st.slider("Hedef kâr oranı (%)", min_value=0, max_value=200, value=30, step=5, key="margin_now")

    # Calculate
    calc = calc_finance(materials_df, labor_hours, hourly_rate,
                        monthly_rent, monthly_util, other_fixed,
                        employee_count, avg_salary, monthly_total_production,
                        batch_size, target_margin_pct, actual_price)

    # Results
    st.markdown("---")
    st.subheader("📊 Sonuçlar — Now")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Toplam maliyet (batch)", f"{calc['total_cost']:.2f} ₺")
    r2.metric("Birim maliyet", f"{calc['unit_cost']:.2f} ₺/adet")
    r3.metric("Gerçek gelir", f"{(calc['revenue_now'] or 0):.2f} ₺")
    r4.metric("Kâr (Now)", f"{(calc['profit_now'] or 0):.2f} ₺")

    if st.checkbox("Gider dağılımını göster"):
        shares_df = pd.DataFrame({
            "Kalem": ["Hammadde","İşçilik","Sabit (batch payı)"],
            "Tutar (₺)": [calc["materials_total"], calc["labor_total"], calc["fixed_total_for_batch"]]
        })
        shares_df["Pay (%)"] = (shares_df["Tutar (₺)"] / max(calc["total_cost"], 1e-9) * 100).round(1)
        st.dataframe(shares_df, use_container_width=True)

    if use_ai and api_key:
        prompt = build_prompt(product_name, batch_size, target_margin_pct, actual_price, calc, note="Now senaryosu")
        comment = ai_commentary(prompt)
        if comment:
            st.markdown("#### 💬 AI Yorumu")
            st.write(comment)

    # Save NOW
    if st.button("💾 Kaydet (Now)"):
        payload = {
            "record_date": record_date.isoformat(),
            "year_month": f"{record_date.year:04d}-{record_date.month:02d}",
            "scenario": "now",
            "product_name": product_name,
            "batch_size": int(batch_size),
            "materials_json": materials_df.to_json(orient="records", force_ascii=False),
            "labor_hours": float(labor_hours),
            "hourly_rate": float(hourly_rate),
            "monthly_rent": float(monthly_rent),
            "monthly_util": float(monthly_util),
            "other_fixed": float(other_fixed),
            "employee_count": int(employee_count),
            "avg_salary": float(avg_salary),
            "monthly_total_production": int(monthly_total_production),
            "target_margin_pct": float(target_margin_pct),
            "actual_price": float(actual_price),
            "materials_total": float(calc["materials_total"]),
            "labor_total": float(calc["labor_total"]),
            "fixed_total_for_batch": float(calc["fixed_total_for_batch"]),
            "total_cost": float(calc["total_cost"]),
            "unit_cost": float(calc["unit_cost"]),
            "recommended_price": float(calc["recommended_price"]),
            "revenue": float(calc["revenue_now"] or 0),
            "profit": float(calc["profit_now"] or 0),
            "created_at": datetime.utcnow().isoformat(timespec="seconds")
        }
        save_record(payload)
        st.success("Now kaydı oluşturuldu ✅")

# ---------------------------
# Page: WHAT-IF
# ---------------------------
elif page == "What‑If (Senaryo)":
    st.header("What‑If — Senaryo Analizi")
    st.write("**What‑If**: Gerçek satış fiyatı yerine **hedef kâr** belirleyip önerilen fiyat ve beklenen kârı görürsün; kayıt **senaryo** olarak saklanır.")

    col_top = st.columns(4)
    with col_top[0]:
        product_name = st.text_input("Ürün adı", value="Lavanta Sabunu", key="p_wi")
    with col_top[1]:
        record_date = st.date_input("Senaryo Tarihi", value=date.today(), key="d_wi")
    with col_top[2]:
        batch_size = st.number_input("Batch size (senaryo)", min_value=1, value=10, step=1, key="b_wi")
    with col_top[3]:
        target_margin_pct = st.slider("Hedef kâr (%)", min_value=0, max_value=200, value=40, step=5, key="m_wi")

    st.markdown("### 🧴 Malzeme Giderleri (senaryo)")
    materials_df = materials_editor(key="mat_wi")

    st.markdown("### 🧍‍♀️ İşçilik Giderleri (senaryo)")
    c1, c2 = st.columns(2)
    with c1:
        labor_hours = st.number_input("Toplam üretim süresi (saat)", min_value=0.0, value=1.0, step=0.5, key="lh_wi")
    with c2:
        hourly_rate = st.number_input("Saatlik ücret (₺/saat)", min_value=0.0, value=200.0, step=10.0, key="hr_wi")

    st.markdown("### 🏭 Sabit Giderler (Aylık, senaryo)")
    f1, f2 = st.columns(2)
    with f1:
        monthly_rent = st.number_input("Kira (₺/ay)", min_value=0.0, value=5000.0, step=100.0, key="rent_wi")
        monthly_util = st.number_input("Elektrik/Su/Doğalgaz (₺/ay)", min_value=0.0, value=800.0, step=50.0, key="util_wi")
        other_fixed = st.number_input("Diğer sabit giderler (₺/ay)", min_value=0.0, value=200.0, step=50.0, key="other_wi")
    with f2:
        employee_count = st.number_input("Çalışan sayısı", min_value=0, value=0, step=1, key="emp_wi")
        avg_salary = st.number_input("Ortalama maaş (₺/çalışan/ay)", min_value=0.0, value=0.0, step=100.0, key="sal_wi")
        monthly_total_production = st.number_input("Aylık toplam üretim adedi (tüm ürünler)", min_value=1, value=500, step=10, key="prod_wi")

    calc = calc_finance(materials_df, labor_hours, hourly_rate,
                        monthly_rent, monthly_util, other_fixed,
                        employee_count, avg_salary, monthly_total_production,
                        batch_size, target_margin_pct, actual_price=None)

    st.markdown("---")
    st.subheader("📊 Sonuçlar — What‑If")
    r1, r2, r3 = st.columns(3)
    r1.metric("Toplam maliyet (batch)", f"{calc['total_cost']:.2f} ₺")
    r2.metric("Birim maliyet", f"{calc['unit_cost']:.2f} ₺/adet")
    r3.metric(f"Önerilen fiyat (%{int(target_margin_pct)})", f"{calc['recommended_price']:.2f} ₺/adet")

    expected_revenue = calc["recommended_price"] * batch_size
    expected_profit = expected_revenue - calc["total_cost"]
    st.metric("Beklenen kâr (senaryo)", f"{expected_profit:.2f} ₺")

    if use_ai and api_key:
        prompt = build_prompt(product_name, batch_size, target_margin_pct, None, calc, note="What‑If senaryosu")
        comment = ai_commentary(prompt)
        if comment:
            st.markdown("#### 💬 AI Yorumu")
            st.write(comment)

    if st.button("💾 Kaydet (What‑If)"):
        payload = {
            "record_date": record_date.isoformat(),
            "year_month": f"{record_date.year:04d}-{record_date.month:02d}",
            "scenario": "what_if",
            "product_name": product_name,
            "batch_size": int(batch_size),
            "materials_json": materials_df.to_json(orient="records", force_ascii=False),
            "labor_hours": float(labor_hours),
            "hourly_rate": float(hourly_rate),
            "monthly_rent": float(monthly_rent),
            "monthly_util": float(monthly_util),
            "other_fixed": float(other_fixed),
            "employee_count": int(employee_count),
            "avg_salary": float(avg_salary),
            "monthly_total_production": int(monthly_total_production),
            "target_margin_pct": float(target_margin_pct),
            "actual_price": None,
            "materials_total": float(calc["materials_total"]),
            "labor_total": float(calc["labor_total"]),
            "fixed_total_for_batch": float(calc["fixed_total_for_batch"]),
            "total_cost": float(calc["total_cost"]),
            "unit_cost": float(calc["unit_cost"]),
            "recommended_price": float(calc["recommended_price"]),
            "revenue": float(expected_revenue),
            "profit": float(expected_profit),
            "created_at": datetime.utcnow().isoformat(timespec="seconds")
        }
        save_record(payload)
        st.success("What‑If kaydı oluşturuldu ✅")

# ---------------------------
# Page: History & Reports
# ---------------------------
elif page == "Geçmiş & Raporlar":
    st.header("📒 Geçmiş & Aylık Raporlar")
    all_df = load_all(limit=1000)
    if all_df.empty:
        st.info("Henüz kayıt yok. **Now** veya **What‑If** sayfasından kayıt oluşturun.")
    else:
        months = sorted(all_df["year_month"].unique())
        sel_month = st.selectbox("Ay seç (YYYY‑MM)", months, index=0)

        month_df = load_month(sel_month)
        st.markdown(f"### {sel_month} — Kayıtlar")
        view_cols = ["record_date","scenario","product_name","batch_size","unit_cost","recommended_price","actual_price","revenue","total_cost","profit"]
        st.dataframe(month_df[view_cols], use_container_width=True)

        agg = month_df.groupby("scenario").agg(
            toplam_gelir=("revenue","sum"),
            toplam_maliyet=("total_cost","sum"),
            toplam_kar=("profit","sum"),
            kayit_sayisi=("id","count")
        ).reset_index()
        st.markdown("#### Aylık Özet")
        st.dataframe(agg, use_container_width=True)

        try:
            import matplotlib.pyplot as plt
            day_df = month_df.copy()
            day_df["record_date"] = pd.to_datetime(day_df["record_date"]).dt.date
            daily = day_df.groupby("record_date")["profit"].sum().reset_index()

            fig = plt.figure(figsize=(6,3))
            plt.plot(daily["record_date"], daily["profit"])
            plt.title("Günlük Toplam Kâr")
            plt.xlabel("Tarih")
            plt.ylabel("Kâr (₺)")
            st.pyplot(fig)

            fig2 = plt.figure(figsize=(6,3))
            sc = month_df.groupby("scenario")["profit"].sum().reset_index()
            plt.bar(sc["scenario"], sc["profit"])
            plt.title("Senaryoya Göre Kâr")
            plt.xlabel("Senaryo")
            plt.ylabel("Kâr (₺)")
            st.pyplot(fig2)
        except Exception as e:
            st.info("Grafikler oluşturulamadı: " + str(e))

        csv_buf = StringIO()
        month_df.to_csv(csv_buf, index=False)
        st.download_button("Bu ayın tüm kayıtlarını CSV indir", data=csv_buf.getvalue(), file_name=f"kayitlar_{sel_month}.csv", mime="text/csv")

# ---------------------------
# Page: Help
# ---------------------------
else:
    st.header("❓ Yardım / Kullanım Kılavuzu")
    st.markdown("""
**Gezinti**
- **Now (Gerçek durum):** Gerçek satış fiyatı ile kâr/zararı hesaplar ve **kaydeder**.
- **What‑If (Senaryo):** Hedef kâra göre önerilen fiyat ve beklenen kârı **simüle eder**; ayrı kayıt edilir.
- **Geçmiş & Raporlar:** Ay bazında tüm kayıtları listeler, günlük kâr grafiği ve senaryo bazlı kâr dağılımı sunar.

**Tarih & Ay mantığı**
- Kayıtlar seçilen **tarih** ile saklanır; ay bazlı rapor için `YYYY‑MM` kullanılır.

**Sabit giderlerin payı**
- Kira, fatura, maaş gibi giderler aylık toplamdan **ürün başına** paylaştırılır (Aylık toplam üretim adedine göre).

**AI Yorumu (opsiyonel)**
- Ücretsiz Groq anahtarıyla kısa Türkçe yorum alabilirsiniz (sağda sağlayıcı seçin).
- Anahtar girilmezse uygulama onsuz çalışır.

**Veri saklama**
- Veriler `mini_fiyat.db` (SQLite) içinde saklanır.
""")
    st.info("İpucu: **Now** ve **What‑If** senaryolarını ayrı kaydetmek, geçmişte fiili sonuçlarla planların farkını görmenizi sağlar.")

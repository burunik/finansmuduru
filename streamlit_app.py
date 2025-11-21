
import os
import json
from datetime import date, datetime
from io import StringIO

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Mini Fiyat Analizcisi Pro", page_icon="?妙", layout="wide")
st.title("?妙 Mini Fiyat Analizcisi Pro")
st.caption("Neon/PostgreSQL ile kal覺c覺 kay覺t, tarih bazl覺 maliyet takibi, ayl覺k k璽r/zarar ve **Now vs What?f** senaryolar覺")

PG_DSN = os.getenv("PG_DSN")

@st.cache_resource(show_spinner=False)
def get_engine():
    if not PG_DSN:
        raise RuntimeError("PG_DSN ortam de?i?keni tan覺ml覺 de?il. Streamlit Secrets'e PG_DSN connection string ekleyin.")
    eng = create_engine(PG_DSN, pool_pre_ping=True)
    return eng

def init_db():
    eng = get_engine()
    with eng.begin() as con:
        con.execute(text("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
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
        """))

def save_record(payload: dict):
    eng = get_engine()
    cols = ",".join(payload.keys())
    qmarks = ",".join([f":{c}" for c in payload.keys()])
    stmt = text(f"INSERT INTO records ({cols}) VALUES ({qmarks})")
    with eng.begin() as con:
        con.execute(stmt, payload)

def load_month(year_month: str):
    eng = get_engine()
    query = text("SELECT * FROM records WHERE year_month = :ym ORDER BY record_date DESC, id DESC")
    df = pd.read_sql_query(query, eng, params={"ym": year_month})
    return df

def load_all(limit=500):
    eng = get_engine()
    query = text("SELECT * FROM records ORDER BY record_date DESC, id DESC LIMIT :lim")
    df = pd.read_sql_query(query, eng, params={"lim": limit})
    return df

try:
    init_db()
except Exception as e:
    st.error(f"Veritaban覺 ba?lant覺 hatas覺: {e}")
    st.stop()

from openai import OpenAI

def calc_finance(materials_df: pd.DataFrame, labor_hours: float, hourly_rate: float,
                 monthly_rent: float, monthly_util: float, other_fixed: float,
                 employee_count: int, avg_salary: float, monthly_total_production: int,
                 batch_size: int, target_margin_pct: float, actual_price: float | None):
    df = materials_df.copy()
    if len(df.columns) == 0:
        df = pd.DataFrame(columns=["Malzeme","Miktar","Birim","Birim Fiyat覺 (??"])
    if "Tutar (??" not in df.columns:
        df["Tutar (??"] = 0.0
    df["Tutar (??"] = df.get("Miktar", 0).fillna(0) * df.get("Birim Fiyat覺 (??", 0).fillna(0)
    materials_total = float(df["Tutar (??"].sum())

    labor_total = float(labor_hours * hourly_rate)

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

st.sidebar.header("?? Gezinti")
page = st.sidebar.radio("Sayfa", ["Now (Ger癟ek durum)", "What?f (Senaryo)", "Ge癟mi? & Raporlar", "Yard覺m"])

st.sidebar.markdown("---")
st.sidebar.header("?? AI Yorumu (opsiyonel)")
use_ai = st.sidebar.checkbox("AI yorumu 羹ret")
provider = st.sidebar.selectbox("Sa?lay覺c覺", ["Groq (羹cretsiz)", "OpenAI"], index=0)
if provider == "Groq (羹cretsiz)":
    ai_base = "https://api.groq.com/openai/v1"
    ai_model = st.sidebar.selectbox("Model", ["llama3-8b-8192"], index=0)
    api_key_label = "GROQ_API_KEY"
else:
    ai_base = "https://api.openai.com/v1"
    ai_model = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-4o"], index=0)
    api_key_label = "OPENAI_API_KEY"
api_key = st.sidebar.text_input(api_key_label, type="password", help="Anahtar覺n覺 buraya gir.")

st.sidebar.markdown("---")
st.sidebar.caption("? 襤pucu: **Now** ger癟ek verileri, **What?f** senaryolar覺 ayr覺 kaydeder.")

def materials_editor(default_rows=None, key="materials"):
    if default_rows is None:
        default_rows = [
            {"Malzeme": "Zeytinya?覺", "Miktar": 200.0, "Birim": "g", "Birim Fiyat覺 (??": 0.12},
            {"Malzeme": "Lavanta Ya?覺", "Miktar": 10.0, "Birim": "ml", "Birim Fiyat覺 (??": 1.50},
            {"Malzeme": "Ambalaj", "Miktar": 1.0, "Birim": "adet", "Birim Fiyat覺 (??": 5.00},
        ]
    df = st.data_editor(pd.DataFrame(default_rows), num_rows="dynamic", use_container_width=True, key=key)
    return df

def ai_commentary(prompt: str):
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
        st.warning(f"AI yorumu al覺namad覺: {e}")
        return ""

def build_prompt(product_name, batch_size, target_margin_pct, actual_price,
                 calc, note=""):
    return f"""
A?a?覺daki maliyet analizi i癟in T羹rk癟e, 3-5 c羹mle ile k覺sa ve net bir yorum yaz.
- En y羹ksek maliyet kalemini belirt.
- K覺sa bir iyile?tirme 繹nerisi yap (繹r. batch b羹y羹tmek, birim fiyat pazarl覺?覺).
- Hedef k璽ra g繹re sat覺? fiyat覺 mant覺kl覺 m覺 de?erlendir.

?r羹n: {product_name}
Batch: {batch_size} adet
Birim maliyet: {calc['unit_cost']:.2f} ???nerilen sat覺? fiyat覺 (%{int(target_margin_pct)} k璽r): {calc['recommended_price']:.2f} ??Ger癟ek sat覺? fiyat覺: {('?? if actual_price in (None, 0) else f'{actual_price:.2f} ??)}
Hammadde: {calc['materials_total']} ??襤?癟ilik: {calc['labor_total']} ??Sabit gider (batch pay覺): {calc['fixed_total_for_batch']} ??Toplam: {calc['total_cost']} ??Not: {note}
""".strip()

if page == "Now (Ger癟ek durum)":
    st.header("Now ??Ger癟ek ?retim ve Sat覺?")
    st.write("**Now**: Ger癟ek maliyetleri ve **fiili sat覺? fiyat覺n覺** girersin; k璽r/zarar覺 hesaplar ve tarih ile kaydeder.")

    col_top = st.columns(4)
    with col_top[0]:
        product_name = st.text_input("?r羹n ad覺", value="Lavanta Sabunu")
    with col_top[1]:
        record_date = st.date_input("Tarih", value=date.today())
    with col_top[2]:
        batch_size = st.number_input("Bu 羹retimdeki adet (batch size)", min_value=1, value=10, step=1)
    with col_top[3]:
        actual_price = st.number_input("Ger癟ek sat覺? fiyat覺 (??adet)", min_value=0.0, value=70.0, step=1.0)

    st.markdown("### ?妥 Malzeme Giderleri")
    materials_df = materials_editor(key="mat_now")

    st.markdown("### ????儭?襤?癟ilik Giderleri")
    c1, c2 = st.columns(2)
    with c1:
        labor_hours = st.number_input("Toplam 羹retim s羹resi (saat)", min_value=0.0, value=1.0, step=0.5, key="labor_hours_now")
    with c2:
        hourly_rate = st.number_input("Saatlik 羹cret (??saat)", min_value=0.0, value=200.0, step=10.0, key="hourly_rate_now")

    st.markdown("### ? Sabit Giderler (Ayl覺k)")
    f1, f2 = st.columns(2)
    with f1:
        monthly_rent = st.number_input("Kira (??ay)", min_value=0.0, value=5000.0, step=100.0, key="rent_now")
        monthly_util = st.number_input("Elektrik/Su/Do?algaz (??ay)", min_value=0.0, value=800.0, step=50.0, key="util_now")
        other_fixed = st.number_input("Di?er sabit giderler (??ay)", min_value=0.0, value=200.0, step=50.0, key="other_now")
    with f2:
        employee_count = st.number_input("?al覺?an say覺s覺", min_value=0, value=0, step=1, key="emp_now")
        avg_salary = st.number_input("Ortalama maa? (??癟al覺?an/ay)", min_value=0.0, value=0.0, step=100.0, key="sal_now")
        monthly_total_production = st.number_input("Ayl覺k toplam 羹retim adedi (t羹m 羹r羹nler)", min_value=1, value=500, step=10, key="prod_now")

    st.markdown("### ? Hedef K璽r (kar?覺la?t覺rma i癟in)")
    target_margin_pct = st.slider("Hedef k璽r oran覺 (%)", min_value=0, max_value=200, value=30, step=5, key="margin_now")

    calc = calc_finance(materials_df, labor_hours, hourly_rate,
                        monthly_rent, monthly_util, other_fixed,
                        employee_count, avg_salary, monthly_total_production,
                        batch_size, target_margin_pct, actual_price)

    st.markdown("---")
    st.subheader("?? Sonu癟lar ??Now")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Toplam maliyet (batch)", f"{calc['total_cost']:.2f} ??)
    r2.metric("Birim maliyet", f"{calc['unit_cost']:.2f} ??adet")
    r3.metric("Ger癟ek gelir", f"{(calc['revenue_now'] or 0):.2f} ??)
    r4.metric("K璽r (Now)", f"{(calc['profit_now'] or 0):.2f} ??)

    if st.checkbox("Gider da?覺l覺m覺n覺 g繹ster"):
        shares_df = pd.DataFrame({
            "Kalem": ["Hammadde","襤?癟ilik","Sabit (batch pay覺)"],
            "Tutar (??": [calc["materials_total"], calc["labor_total"], calc["fixed_total_for_batch"]]
        })
        shares_df["Pay (%)"] = (shares_df["Tutar (??"] / max(calc["total_cost"], 1e-9) * 100).round(1)
        st.dataframe(shares_df, use_container_width=True)

    if use_ai and api_key:
        prompt = build_prompt(product_name, batch_size, target_margin_pct, actual_price, calc, note="Now senaryosu")
        comment = ai_commentary(prompt)
        if comment:
            st.markdown("#### ? AI Yorumu")
            st.write(comment)

    if st.button("? Kaydet (Now)"):
        payload = {
            "record_date": record_date.isoformat(),
            "year_month": ym_from_date(record_date),
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
        st.success("Now kayd覺 olu?turuldu ??)

elif page == "What?f (Senaryo)":
    st.header("What?f ??Senaryo Analizi")
    st.write("**What?f**: Hedef k璽ra g繹re 繹nerilen fiyat ve beklenen k璽r覺 sim羹le eder; kay覺t **senaryo** olarak saklan覺r.")

    col_top = st.columns(4)
    with col_top[0]:
        product_name = st.text_input("?r羹n ad覺", value="Lavanta Sabunu", key="p_wi")
    with col_top[1]:
        record_date = st.date_input("Senaryo Tarihi", value=date.today(), key="d_wi")
    with col_top[2]:
        batch_size = st.number_input("Batch size (senaryo)", min_value=1, value=10, step=1, key="b_wi")
    with col_top[3]:
        target_margin_pct = st.slider("Hedef k璽r (%)", min_value=0, max_value=200, value=40, step=5, key="m_wi")

    st.markdown("### ?妥 Malzeme Giderleri (senaryo)")
    materials_df = materials_editor(key="mat_wi")

    st.markdown("### ????儭?襤?癟ilik Giderleri (senaryo)")
    c1, c2 = st.columns(2)
    with c1:
        labor_hours = st.number_input("Toplam 羹retim s羹resi (saat)", min_value=0.0, value=1.0, step=0.5, key="lh_wi")
    with c2:
        hourly_rate = st.number_input("Saatlik 羹cret (??saat)", min_value=0.0, value=200.0, step=10.0, key="hr_wi")

    st.markdown("### ? Sabit Giderler (Ayl覺k, senaryo)")
    f1, f2 = st.columns(2)
    with f1:
        monthly_rent = st.number_input("Kira (??ay)", min_value=0.0, value=5000.0, step=100.0, key="rent_wi")
        monthly_util = st.number_input("Elektrik/Su/Do?algaz (??ay)", min_value=0.0, value=800.0, step=50.0, key="util_wi")
        other_fixed = st.number_input("Di?er sabit giderler (??ay)", min_value=0.0, value=200.0, step=50.0, key="other_wi")
    with f2:
        employee_count = st.number_input("?al覺?an say覺s覺", min_value=0, value=0, step=1, key="emp_wi")
        avg_salary = st.number_input("Ortalama maa? (??癟al覺?an/ay)", min_value=0.0, value=0.0, step=100.0, key="sal_wi")
        monthly_total_production = st.number_input("Ayl覺k toplam 羹retim adedi (t羹m 羹r羹nler)", min_value=1, value=500, step=10, key="prod_wi")

    calc = calc_finance(materials_df, labor_hours, hourly_rate,
                        monthly_rent, monthly_util, other_fixed,
                        employee_count, avg_salary, monthly_total_production,
                        batch_size, target_margin_pct, actual_price=None)

    st.markdown("---")
    st.subheader("?? Sonu癟lar ??What?f")
    r1, r2, r3 = st.columns(3)
    r1.metric("Toplam maliyet (batch)", f"{calc['total_cost']:.2f} ??)
    r2.metric("Birim maliyet", f"{calc['unit_cost']:.2f} ??adet")
    r3.metric(f"?nerilen fiyat (%{int(target_margin_pct)})", f"{calc['recommended_price']:.2f} ??adet")

    expected_revenue = calc["recommended_price"] * batch_size
    expected_profit = expected_revenue - calc["total_cost"]
    st.metric("Beklenen k璽r (senaryo)", f"{expected_profit:.2f} ??)

    if use_ai and api_key:
        prompt = build_prompt(product_name, batch_size, target_margin_pct, None, calc, note="What?f senaryosu")
        comment = ai_commentary(prompt)
        if comment:
            st.markdown("#### ? AI Yorumu")
            st.write(comment)

    if st.button("? Kaydet (What?f)"):
        payload = {
            "record_date": record_date.isoformat(),
            "year_month": ym_from_date(record_date),
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
        st.success("What?f kayd覺 olu?turuldu ??)

elif page == "Ge癟mi? & Raporlar":
    st.header("?? Ge癟mi? & Ayl覺k Raporlar")
    all_df = load_all(limit=1000)
    if all_df.empty:
        st.info("Hen羹z kay覺t yok. **Now** veya **What?f** sayfas覺ndan kay覺t olu?turun.")
    else:
        months = sorted(all_df["year_month"].unique())
        sel_month = st.selectbox("Ay se癟 (YYYY?M)", months, index=0)

        month_df = load_month(sel_month)
        st.markdown(f"### {sel_month} ??Kay覺tlar")
        view_cols = ["record_date","scenario","product_name","batch_size","unit_cost","recommended_price","actual_price","revenue","total_cost","profit"]
        st.dataframe(month_df[view_cols], use_container_width=True)

        agg = month_df.groupby("scenario").agg(
            toplam_gelir=("revenue","sum"),
            toplam_maliyet=("total_cost","sum"),
            toplam_kar=("profit","sum"),
            kayit_sayisi=("id","count")
        ).reset_index()
        st.markdown("#### Ayl覺k ?zet")
        st.dataframe(agg, use_container_width=True)

        try:
            import matplotlib.pyplot as plt
            day_df = month_df.copy()
            day_df["record_date"] = pd.to_datetime(day_df["record_date"]).dt.date
            daily = day_df.groupby("record_date")["profit"].sum().reset_index()

            fig = plt.figure(figsize=(6,3))
            plt.plot(daily["record_date"], daily["profit"])
            plt.title("G羹nl羹k Toplam K璽r")
            plt.xlabel("Tarih")
            plt.ylabel("K璽r (??")
            st.pyplot(fig)

            fig2 = plt.figure(figsize=(6,3))
            sc = month_df.groupby("scenario")["profit"].sum().reset_index()
            plt.bar(sc["scenario"], sc["profit"])
            plt.title("Senaryoya G繹re K璽r")
            plt.xlabel("Senaryo")
            plt.ylabel("K璽r (??")
            st.pyplot(fig2)
        except Exception as e:
            st.info("Grafikler olu?turulamad覺: " + str(e))

        csv_buf = StringIO()
        month_df.to_csv(csv_buf, index=False)
        st.download_button("Bu ay覺n t羹m kay覺tlar覺n覺 CSV indir", data=csv_buf.getvalue(), file_name=f"kayitlar_{sel_month}.csv", mime="text/csv")

else:
    st.header("??Yard覺m / Kullan覺m K覺lavuzu")
    st.markdown("""
**Gezinti**
- **Now (Ger癟ek durum):** Ger癟ek sat覺? fiyat覺 ile k璽r/zarar覺 hesaplar ve **Neon/Postgres'e kaydeder**.
- **What?f (Senaryo):** Hedef k璽ra g繹re 繹nerilen fiyat ve beklenen k璽r覺 **sim羹le eder**; ayr覺 kay覺t edilir.
- **Ge癟mi? & Raporlar:** Ay baz覺nda t羹m kay覺tlar覺 listeler, g羹nl羹k k璽r grafi?i ve senaryo bazl覺 k璽r da?覺l覺m覺 sunar.

**Neon Ayar覺 (PG_DSN)**
- Neon'da bir proje a癟覺n, connection string'i kopyalay覺n.
- Streamlit Cloud'da **Settings ??Secrets** k覺sm覺na ?u ?ekilde ekleyin:
  `PG_DSN = "postgresql://kullanici:parola@host/dbadiniz"`

**Sabit giderlerin pay覺**
- Kira, fatura, maa? gibi giderler ayl覺k toplamdan **羹r羹n ba?覺na** payla?t覺r覺l覺r (Ayl覺k toplam 羹retim adedine g繹re).

**AI Yorumu (opsiyonel)**
- ?cretsiz Groq anahtar覺yla k覺sa T羹rk癟e yorum alabilirsiniz (sa?da sa?lay覺c覺 se癟in).
- Anahtar girilmezse uygulama onsuz 癟al覺?覺r.
""")
    st.info("襤pucu: **Now** ve **What?f** senaryolar覺n覺 ayr覺 kaydetmek, fiili sonu癟larla planlar覺n fark覺n覺 g繹rmenizi sa?lar.")

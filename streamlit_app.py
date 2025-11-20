
import os
import time
import pandas as pd
import streamlit as st
import math
from io import StringIO, BytesIO

# --- Page Config ---
st.set_page_config(page_title="Mini Fiyat Analizcisi", page_icon="🧮", layout="centered")
st.title("🧮 Mini Fiyat Analizcisi")
st.caption("Küçük üreticiler için basit ama etkili kârlılık aracı — malzeme, işçilik ve sabit giderleri hesaba katar.")

# --- Sidebar: Global Inputs ---
with st.sidebar:
    st.header("🔧 Genel Ayarlar")
    product_name = st.text_input("Ürün adı", value="Lavanta Sabunu")
    batch_size = st.number_input("Bu üretimdeki adet (batch size)", min_value=1, value=10, step=1)
    target_margin_pct = st.slider("Hedef kâr oranı (%)", min_value=0, max_value=200, value=30, step=5)
    st.markdown("---")
    st.subheader("💬 AI yorumu (opsiyonel)")
    use_ai = st.checkbox("AI yorumunu üret (OpenAI API anahtarı gerekli)")
    ai_model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o"], index=0)
    openai_key = st.text_input("OPENAI_API_KEY", type="password", help="İstersen buraya gir; çevrede tanımlıysa boş bırak.")
    st.markdown("---")
    st.caption("💡 İpucu: Sabit giderlerin ürün başına payını hesaplarken aylık toplam üretim tahmininizi doğru girin.")

# --- Section 1: Materials ---
st.subheader("🧴 Malzeme Giderleri")
st.markdown("Her malzeme için **miktar**, **birim (g/ml/adet)** ve **birim fiyat (₺)** girin.")

default_materials = pd.DataFrame([
    {"Malzeme": "Zeytinyağı", "Miktar": 200.0, "Birim": "g", "Birim Fiyatı (₺)": 0.12},
    {"Malzeme": "Lavanta Yağı", "Miktar": 10.0, "Birim": "ml", "Birim Fiyatı (₺)": 1.50},
    {"Malzeme": "Ambalaj", "Miktar": 1.0, "Birim": "adet", "Birim Fiyatı (₺)": 5.00},
])

materials = st.data_editor(
    default_materials,
    num_rows="dynamic",
    use_container_width=True,
    key="materials_editor",
)

# Compute materials total
materials["Tutar (₺)"] = materials["Miktar"].fillna(0) * materials["Birim Fiyatı (₺)"].fillna(0)
materials_total = float(materials["Tutar (₺)"].sum())

# --- Section 2: Labor ---
st.subheader("🧍‍♀️ İşçilik Giderleri")
col_l1, col_l2 = st.columns(2)
with col_l1:
    labor_hours = st.number_input("Toplam üretim süresi (saat)", min_value=0.0, value=1.0, step=0.5)
with col_l2:
    hourly_rate = st.number_input("Saatlik ücret (₺/saat)", min_value=0.0, value=200.0, step=10.0)
labor_total = labor_hours * hourly_rate

# --- Section 3: Fixed Costs ---
st.subheader("🏭 Sabit Giderler (Aylık)")
st.markdown("Aylık giderleri girin. Ürün başına payı **aylık toplam üretim adedinize** göre hesaplanır.")
col_f1, col_f2 = st.columns(2)
with col_f1:
    monthly_rent = st.number_input("Kira (₺/ay)", min_value=0.0, value=5000.0, step=100.0)
    monthly_util = st.number_input("Elektrik/Su/Doğalgaz (₺/ay)", min_value=0.0, value=800.0, step=50.0)
    other_fixed = st.number_input("Diğer sabit giderler (₺/ay)", min_value=0.0, value=200.0, step=50.0)
with col_f2:
    employee_count = st.number_input("Çalışan sayısı", min_value=0, value=0, step=1)
    avg_salary = st.number_input("Ortalama maaş (₺/çalışan/ay)", min_value=0.0, value=0.0, step=100.0, help="Çalışan yoksa 0 girin.")
    monthly_total_production = st.number_input("Aylık toplam üretim adedi (tüm ürünler)", min_value=1, value=500, step=10)

payroll = employee_count * avg_salary
fixed_total_monthly = monthly_rent + monthly_util + other_fixed + payroll
fixed_cost_per_unit_allocation = fixed_total_monthly / monthly_total_production

# --- Calculations ---
materials_total = round(materials_total, 2)
labor_total = round(labor_total, 2)
fixed_total = round(fixed_cost_per_unit_allocation * batch_size, 2)  # allocate to this batch
total_cost = materials_total + labor_total + fixed_total
unit_cost = total_cost / batch_size if batch_size > 0 else 0.0

target_margin = target_margin_pct / 100.0
recommended_price = unit_cost * (1 + target_margin)

# Compute shares
shares = {
    "Hammadde": materials_total,
    "İşçilik": labor_total,
    "Sabit (bu batch payı)": fixed_total,
}
shares_df = pd.DataFrame({"Kalem": list(shares.keys()), "Tutar (₺)": list(shares.values())})
shares_df["Pay (%)"] = (shares_df["Tutar (₺)"] / max(total_cost, 1e-9) * 100).round(1)

# --- Results ---
st.markdown("---")
st.subheader("📊 Sonuçlar")
col_r1, col_r2 = st.columns(2)
with col_r1:
    st.metric("Toplam maliyet (batch)", f"{total_cost:,.2f} ₺")
    st.metric("Birim maliyet", f"{unit_cost:,.2f} ₺/adet")
with col_r2:
    st.metric(f"Önerilen satış fiyatı (%{int(target_margin_pct)} kâr)", f"{recommended_price:,.2f} ₺/adet")
    st.metric("Sabit gider payı (ürün başına)", f"{fixed_cost_per_unit_allocation:,.2f} ₺")

st.markdown("#### Gider Dağılımı")
st.dataframe(shares_df, use_container_width=True)

try:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4,4))
    ax.pie(shares_df["Tutar (₺)"], labels=shares_df["Kalem"], autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
    st.pyplot(fig, use_container_width=False)
except Exception as e:
    st.info("Grafik oluşturulamadı: " + str(e))

# --- AI Commentary (Optional) ---
def build_ai_prompt():
    prompt = f"""
Aşağıdaki küçük işletme maliyet analizi için kısa ve anlaşılır bir yorum yaz (Türkçe, 3-5 cümle, basit dil):
Ürün adı: {product_name}
Batch adet: {batch_size}
Hammadde toplam: {materials_total} ₺
İşçilik toplam: {labor_total} ₺
Sabit gider (bu batch payı): {fixed_total} ₺
Toplam maliyet: {total_cost} ₺
Birim maliyet: {unit_cost:.2f} ₺/adet
Hedef kâr oranı: %{int(target_margin_pct)}
Önerilen satış fiyatı: {recommended_price:.2f} ₺/adet
Sabit giderlerin ürün başına payı: {fixed_cost_per_unit_allocation:.2f} ₺

Yorum şablonu:
- Maliyet yapısındaki en yüksek kalemi belirt.
- Kısa bir iyileştirme önerisi ver (ör. batch büyütmek, satın alma birim fiyatını düşürmek).
- Hedef kâra göre önerilen satış fiyatının mantıklı olup olmadığını değerlendir.
"""
    return prompt.strip()

ai_comment = ""
if use_ai:
    from openai import OpenAI
    key = openai_key or os.getenv("OPENAI_API_KEY", "")
    if not key:
        st.warning("AI için OpenAI API anahtarı girilmedi.")
    else:
        try:
            client = OpenAI(api_key=key)
            with st.spinner("AI yorumu üretiliyor..."):
                resp = client.chat.completions.create(
                    model=ai_model,
                    messages=[
                        {"role":"system","content":"You are a concise business assistant."},
                        {"role":"user","content": build_ai_prompt()}
                    ],
                    temperature=0.5,
                    max_tokens=220
                )
            ai_comment = resp.choices[0].message.content.strip()
            st.markdown("#### 💬 AI Yorumu")
            st.write(ai_comment)
        except Exception as e:
            st.error(f"AI hatası: {e}")

# --- Export Section ---
st.markdown("---")
st.subheader("⬇️ Dışa Aktar")

# Build a concise CSV/TSV for export
summary_df = pd.DataFrame({
    "Alan": ["Ürün", "Batch Adedi", "Hammadde", "İşçilik", "Sabit (batch payı)", "Toplam", "Birim Maliyet", f"Önerilen Fiyat (%{int(target_margin_pct)})"],
    "Değer": [product_name, batch_size, f"{materials_total:.2f}", f"{labor_total:.2f}", f"{fixed_total:.2f}", f"{total_cost:.2f}", f"{unit_cost:.2f}", f"{recommended_price:.2f}"]
})
csv_buf = StringIO()
summary_df.to_csv(csv_buf, index=False)
st.download_button("Özet CSV indir", data=csv_buf.getvalue(), file_name="mini_fiyat_ozet.csv", mime="text/csv")

# Materials CSV
mat_buf = StringIO()
materials.to_csv(mat_buf, index=False)
st.download_button("Malzeme listesi CSV indir", data=mat_buf.getvalue(), file_name="malzemeler.csv", mime="text/csv")

# Markdown export (nice for sharing)
md = []
md.append(f"# {product_name} — Fiyat Analizi\n")
md.append("## Özet\n")
for _, row in summary_df.iterrows():
    md.append(f"- **{row['Alan']}**: {row['Değer']}")
md.append("\n## Gider Dağılımı\n")
for _, row in shares_df.iterrows():
    md.append(f"- {row['Kalem']}: {row['Tutar (₺)']:.2f} ₺ (%{row['Pay (%)']})")
if ai_comment:
    md.append("\n## AI Yorumu\n")
    md.append(ai_comment)
md_text = "\n".join(md)
st.download_button("Markdown raporu indir", data=md_text.encode("utf-8"), file_name="rapor.md", mime="text/markdown")

st.success("Hazır 🎉 — Formu doldurdukça sonuçlar canlı güncellenir. Bu dosyayı Streamlit Cloud'da ücretsiz olarak yayınlayabilirsin.")

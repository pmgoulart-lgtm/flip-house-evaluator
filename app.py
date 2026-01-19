# app.py
import streamlit as st
import pandas as pd
from io import BytesIO
from flip_logic import (
    load_market_data,
    get_sale_price_per_m2,
    estimate_absorption_months,
    calc_business_case,
    calc_optimal_purchase_price,
    stress_test_cases,
)

st.set_page_config(page_title="Flip House Evaluator (PT)", layout="wide")

st.title("🏠 Flip House Evaluator — Portugal (vendas efetivas)")
st.caption("Avaliação conservadora com base em €/m² de **vendas efetivas** (base de conhecimento).")

DATA_FILE_DEFAULT = "Dados Mercado Imob 18Jan26.xlsx"

with st.sidebar:
    st.header("📁 Dados")
    data_file = st.text_input("Ficheiro Excel (base de conhecimento)", value=DATA_FILE_DEFAULT)
    st.divider()
    st.header("⚙️ Parâmetros (editáveis)")
    margem_alvo = st.number_input("Margem líquida alvo (%)", min_value=-50.0, max_value=80.0, value=10.0, step=0.5) / 100.0
    prudencia_venda = st.number_input("Prudência na venda (%)", min_value=-50.0, max_value=20.0, value=-5.0, step=0.5) / 100.0
    contingencia_obra = st.number_input("Contingência de obra (%)", min_value=0.0, max_value=50.0, value=10.0, step=0.5) / 100.0

    st.subheader("Custos adicionais (defaults)")
    taxa_aquisicao = st.number_input("Taxa aquisição (IMT+IS+fees) (%)", min_value=0.0, max_value=20.0, value=8.0, step=0.25) / 100.0
    taxa_venda = st.number_input("Taxa venda (mediação + IVA) (%)", min_value=0.0, max_value=15.0, value=6.15, step=0.25) / 100.0
    taxa_holding = st.number_input("Holding/financeiro (% de compra+obra)", min_value=0.0, max_value=10.0, value=1.5, step=0.1) / 100.0

    st.subheader("Alertas")
    obra_pct_alerta = st.number_input("Alerta: obra > X% do investimento", min_value=5.0, max_value=80.0, value=35.0, step=1.0) / 100.0
    absorcao_alerta_meses = st.number_input("Alerta: absorção > (meses)", min_value=1, max_value=24, value=8, step=1)

# Load market data
@st.cache_data(show_spinner=False)
def _cached_load(path: str) -> pd.DataFrame:
    return load_market_data(path)

try:
    market_df = _cached_load(data_file)
except Exception as e:
    st.error(f"Não foi possível carregar o ficheiro '{data_file}'. Verifica o nome/localização e a estrutura do Excel.\n\nDetalhe: {e}")
    st.stop()

localidades = sorted(market_df["Localidade"].dropna().unique().tolist())

st.subheader("🧾 Inputs")
col1, col2, col3, col4, col5 = st.columns([1, 2, 1, 1, 1])

with col1:
    tipologia = st.selectbox("Tipologia", ["T0", "T1", "T2", "T3", "T4+"])
with col2:
    localidade = st.selectbox("Localidade (concelho)", localidades, index=0 if "Lisboa" not in localidades else localidades.index("Lisboa"))
with col3:
    area_m2 = st.number_input("Área (m²)", min_value=10.0, max_value=500.0, value=60.0, step=1.0)
with col4:
    preco_pedido = st.number_input("Preço pedido (€)", min_value=1_000.0, max_value=5_000_000.0, value=200_000.0, step=1_000.0)
with col5:
    renovacao = st.selectbox("Nível de renovação", ["Baixo", "Médio", "Alto"], index=1)

st.divider()

# Compute sale price / m2 from base knowledge
pv_m2, pv_m2_source = get_sale_price_per_m2(market_df, localidade, tipologia)
abs_meses, abs_source = estimate_absorption_months(market_df, localidade, tipologia)

# Sale price scenarios
venda_bruta = pv_m2 * area_m2
venda_prudente = venda_bruta * (1.0 + prudencia_venda)

# Business case initial
base_params = dict(
    taxa_aquisicao=taxa_aquisicao,
    taxa_venda=taxa_venda,
    taxa_holding=taxa_holding,
    contingencia_obra=contingencia_obra,
    prudencia_venda=prudencia_venda,
    margem_alvo=margem_alvo,
    abs_meses=abs_meses,
    obra_level=renovacao,
)

bc_inicial = calc_business_case(
    compra=preco_pedido,
    area_m2=area_m2,
    venda_m2=pv_m2,
    obra_level=renovacao,
    **base_params,
)

# Optimal purchase price (max) to achieve target net margin on prudent sale
preco_otimo = calc_optimal_purchase_price(
    venda_prudente=bc_inicial["venda_prudente"],
    obra_total=bc_inicial["obra_total"],
    taxa_aquisicao=taxa_aquisicao,
    taxa_holding=taxa_holding,
    taxa_venda=taxa_venda,
    margem_alvo=margem_alvo,
)

bc_otimo = calc_business_case(
    compra=preco_otimo,
    area_m2=area_m2,
    venda_m2=pv_m2,
    obra_level=renovacao,
    **base_params,
)

# Executive label
def label_from_margin(m: float, alvo: float) -> str:
    if m >= alvo:
        return "Atrativo ✅"
    if m >= 0:
        return "Marginal ⚠️"
    return "Não recomendável ❌"

resumo_col1, resumo_col2, resumo_col3 = st.columns([2, 1, 1])
with resumo_col1:
    st.markdown("### 🔎 Resumo executivo")
    st.write(f"**Cenário pedido:** {label_from_margin(bc_inicial['margem_liquida'], margem_alvo)}")
    st.write(f"**Cenário ótimo:** {label_from_margin(bc_otimo['margem_liquida'], margem_alvo)}")
with resumo_col2:
    st.metric("€/m² venda (base)", f"{pv_m2:,.0f} €", help=f"Fonte: {pv_m2_source}")
with resumo_col3:
    st.metric("Absorção (meses)", f"{abs_meses:.0f}", help=f"Fonte: {abs_source}")

# Comparative table
st.markdown("### 📊 Business case — comparação")
rows = [
    ("Preço de compra (€)", bc_inicial["compra"], bc_otimo["compra"]),
    ("Aquisição (IMT+IS+fees) (€)", bc_inicial["aquisicao"], bc_otimo["aquisicao"]),
    ("Obra total (c/ contingência) (€)", bc_inicial["obra_total"], bc_otimo["obra_total"]),
    ("Holding/financeiro (€)", bc_inicial["holding"], bc_otimo["holding"]),
    ("Investimento total (€)", bc_inicial["investimento_total"], bc_otimo["investimento_total"]),
    ("Venda prudente (€)", bc_inicial["venda_prudente"], bc_otimo["venda_prudente"]),
    ("Fee venda (€)", bc_inicial["venda_fee"], bc_otimo["venda_fee"]),
    ("Lucro líquido (€)", bc_inicial["lucro_liquido"], bc_otimo["lucro_liquido"]),
    ("Margem líquida (%)", bc_inicial["margem_liquida"] * 100, bc_otimo["margem_liquida"] * 100),
    ("ROI (%)", bc_inicial["roi"] * 100, bc_otimo["roi"] * 100),
    ("Break-even venda (€)", bc_inicial["breakeven_venda"], bc_otimo["breakeven_venda"]),
]
comp_df = pd.DataFrame(rows, columns=["Métrica", "Cenário (pedido)", "Cenário (ótimo)"])
for c in ["Cenário (pedido)", "Cenário (ótimo)"]:
    comp_df[c] = comp_df[c].apply(lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else x)
st.dataframe(comp_df, use_container_width=True, hide_index=True)

# Alerts
st.markdown("### 🚨 Alertas")
alerts = []
if bc_inicial["margem_liquida"] < margem_alvo:
    alerts.append("Margem líquida abaixo da margem alvo no **cenário pedido**.")
if (bc_inicial["obra_total"] / max(bc_inicial["investimento_total"], 1.0)) > obra_pct_alerta:
    alerts.append("Obra representa uma fatia elevada do investimento (risco de derrapagem).")
if abs_meses > absorcao_alerta_meses:
    alerts.append("Tempo de absorção elevado (risco de liquidez / holding).")
if not alerts:
    st.success("Sem alertas críticos pelos critérios atuais.")
else:
    for a in alerts:
        st.warning(a)

# Stress tests
st.markdown("### 🧪 Stress test (impacto em lucro e margem)")
stress_initial = stress_test_cases(bc_inicial, abs_meses)
stress_opt = stress_test_cases(bc_otimo, abs_meses)

stress_df = pd.DataFrame({
    "Cenário": [s["nome"] for s in stress_initial],
    "Pedido: Lucro (€)": [s["lucro"] for s in stress_initial],
    "Pedido: Margem (%)": [s["margem"]*100 for s in stress_initial],
    "Ótimo: Lucro (€)": [s["lucro"] for s in stress_opt],
    "Ótimo: Margem (%)": [s["margem"]*100 for s in stress_opt],
})
for c in ["Pedido: Lucro (€)", "Ótimo: Lucro (€)"]:
    stress_df[c] = stress_df[c].map(lambda x: f"{x:,.0f}")
for c in ["Pedido: Margem (%)", "Ótimo: Margem (%)"]:
    stress_df[c] = stress_df[c].map(lambda x: f"{x:,.1f}")
st.dataframe(stress_df, use_container_width=True, hide_index=True)

# Assumptions
with st.expander("📌 Assunções e regras (transparente)", expanded=False):
    st.write("**Proxies de tipologia:** T0 → T1/Inf.; T4+ → T3 (ou Total se T3 não existir).")
    st.write(f"**Prudência na venda:** {prudencia_venda*100:.1f}% (aplicada ao preço estimado por m²).")
    st.write(f"**Obra por m²:** Baixo 300€ | Médio 600€ | Alto 900€; com contingência {contingencia_obra*100:.1f}%.")
    st.write(f"**Taxa aquisição:** {taxa_aquisicao*100:.2f}% | **Taxa venda:** {taxa_venda*100:.2f}% | **Holding:** {taxa_holding*100:.2f}% (sobre compra+obra).")
    st.write("**Base de dados:** €/m² e absorção são de vendas efetivas por concelho (não anúncios).")

# Export
st.markdown("### ⬇️ Exportar")
export_payload = {
    "inputs": {
        "tipologia": tipologia,
        "localidade": localidade,
        "area_m2": area_m2,
        "preco_pedido": preco_pedido,
        "renovacao": renovacao,
        "margem_alvo": margem_alvo,
        "prudencia_venda": prudencia_venda,
        "contingencia_obra": contingencia_obra,
        "taxa_aquisicao": taxa_aquisicao,
        "taxa_venda": taxa_venda,
        "taxa_holding": taxa_holding,
        "absorcao_meses": abs_meses,
        "pv_m2_base": pv_m2,
    },
    "cenarios": {
        "pedido": bc_inicial,
        "otimo": bc_otimo,
    },
    "stress": {
        "pedido": stress_initial,
        "otimo": stress_opt,
    },
}

# CSV
csv_rows = []
for k, v in export_payload["inputs"].items():
    csv_rows.append(("input", k, v))
for scen in ["pedido", "otimo"]:
    for k, v in export_payload["cenarios"][scen].items():
        csv_rows.append((f"cenario_{scen}", k, v))
csv_df = pd.DataFrame(csv_rows, columns=["secao", "campo", "valor"])

csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
st.download_button("Download CSV", data=csv_bytes, file_name="flip_business_case.csv", mime="text/csv")

# XLSX
bio = BytesIO()
with pd.ExcelWriter(bio, engine="openpyxl") as writer:
    pd.DataFrame([export_payload["inputs"]]).to_excel(writer, index=False, sheet_name="inputs")
    pd.DataFrame([export_payload["cenarios"]["pedido"]]).to_excel(writer, index=False, sheet_name="cenario_pedido")
    pd.DataFrame([export_payload["cenarios"]["otimo"]]).to_excel(writer, index=False, sheet_name="cenario_otimo")
    pd.DataFrame(stress_initial).to_excel(writer, index=False, sheet_name="stress_pedido")
    pd.DataFrame(stress_opt).to_excel(writer, index=False, sheet_name="stress_otimo")
bio.seek(0)
st.download_button("Download Excel", data=bio.getvalue(), file_name="flip_business_case.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

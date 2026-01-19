# flip_logic.py
from __future__ import annotations

import math
import pandas as pd
from typing import Tuple, Dict, Any, List

# Renovation cost mapping (€/m²)
RENOVATION_COSTS = {
    "Baixo": 300.0,
    "Médio": 600.0,
    "Alto": 900.0,
}

TIPOLOGY_MAP = {
    "T0": "T1",     # proxy (Apt. T1 ou Inf.)
    "T1": "T1",
    "T2": "T2",
    "T3": "T3",
    "T4+": "T3",    # proxy (or Total fallback)
}

def load_market_data(path: str) -> pd.DataFrame:
    """
    Loads the knowledge base Excel into a clean dataframe with columns:
    Localidade, Preco_m2_Total, Preco_m2_T1, Preco_m2_T2, Preco_m2_T3, Preco_m2_Moradia,
    Absorcao_Total, Absorcao_T1, Absorcao_T2, Absorcao_T3, Absorcao_Moradia
    """
    df = pd.read_excel(path)

    # The provided file uses multi-row headers and unnamed columns.
    # We normalize by renaming columns to expected positions (based on observed layout).
    if df.shape[1] < 23:
        raise ValueError("Estrutura do Excel inesperada (número de colunas diferente do esperado).")

    df2 = df.copy()
    df2.columns = [
        "Regiao","Localidade","_",
        "Fogos_Total","Fogos_T1","Fogos_T2","Fogos_T3","Fogos_Moradia",
        "Preco_m2_Total","Preco_m2_T1","Preco_m2_T2","Preco_m2_T3","Preco_m2_Moradia",
        "Preco_Fogo_Total","_1","_2","_3","_4",
        "Absorcao_Total","Absorcao_T1","Absorcao_T2","Absorcao_T3","Absorcao_Moradia"
    ]

    # Keep rows with a Localidade and numeric price/m2
    df2 = df2[df2["Localidade"].notna()].copy()
    df2["Preco_m2_Total"] = pd.to_numeric(df2["Preco_m2_Total"], errors="coerce")
    df2 = df2[df2["Preco_m2_Total"].notna()].copy()

    # Coerce relevant columns
    for c in ["Preco_m2_T1","Preco_m2_T2","Preco_m2_T3","Preco_m2_Moradia",
              "Absorcao_Total","Absorcao_T1","Absorcao_T2","Absorcao_T3","Absorcao_Moradia"]:
        df2[c] = pd.to_numeric(df2[c], errors="coerce")

    # Trim Localidade strings
    df2["Localidade"] = df2["Localidade"].astype(str).str.strip()

    # Drop potential "Total" rows for region if they appear duplicated—keep as they can be useful.
    return df2.reset_index(drop=True)

def _pick_row(df: pd.DataFrame, localidade: str) -> pd.Series:
    match = df[df["Localidade"].str.casefold() == localidade.casefold()]
    if match.empty:
        raise ValueError(f"Localidade '{localidade}' não encontrada no Excel.")
    return match.iloc[0]

def get_sale_price_per_m2(df: pd.DataFrame, localidade: str, tipologia: str) -> Tuple[float, str]:
    row = _pick_row(df, localidade)

    t = TIPOLOGY_MAP.get(tipologia, "Total")
    if t == "T1":
        val = row.get("Preco_m2_T1")
        if pd.notna(val):
            return float(val), "Apt. T1 (ou inf.)"
    if t == "T2":
        val = row.get("Preco_m2_T2")
        if pd.notna(val):
            return float(val), "Apt. T2"
    if t == "T3":
        val = row.get("Preco_m2_T3")
        if pd.notna(val):
            return float(val), "Apt. T3 (proxy p/ T4+)"
    # fallback
    return float(row["Preco_m2_Total"]), "Total (fallback)"

def estimate_absorption_months(df: pd.DataFrame, localidade: str, tipologia: str) -> Tuple[float, str]:
    row = _pick_row(df, localidade)
    t = TIPOLOGY_MAP.get(tipologia, "Total")
    col_map = {"T1": "Absorcao_T1", "T2": "Absorcao_T2", "T3": "Absorcao_T3"}
    col = col_map.get(t, None)
    if col and pd.notna(row.get(col)):
        return float(row[col]), f"{col}"
    if pd.notna(row.get("Absorcao_Total")):
        return float(row["Absorcao_Total"]), "Absorcao_Total (fallback)"
    return 6.0, "Default 6 (sem dados)"

def calc_business_case(
    compra: float,
    area_m2: float,
    venda_m2: float,
    obra_level: str,
    taxa_aquisicao: float,
    taxa_venda: float,
    taxa_holding: float,
    contingencia_obra: float,
    prudencia_venda: float,
    margem_alvo: float,
    abs_meses: float,
) -> Dict[str, float]:
    # Sale
    venda_bruta = venda_m2 * area_m2
    venda_prudente = venda_bruta * (1.0 + prudencia_venda)

    # Work
    base_cost = RENOVATION_COSTS.get(obra_level, RENOVATION_COSTS["Médio"])
    obra_base = base_cost * area_m2
    obra_total = obra_base * (1.0 + contingencia_obra)

    # Costs
    aquisicao = compra * taxa_aquisicao
    holding = (compra + obra_total) * taxa_holding
    investimento_total = compra + aquisicao + obra_total + holding
    venda_fee = venda_prudente * taxa_venda

    lucro_liquido = venda_prudente - (investimento_total + venda_fee)
    margem_liquida = lucro_liquido / venda_prudente if venda_prudente > 0 else float("nan")
    roi = lucro_liquido / investimento_total if investimento_total > 0 else float("nan")

    breakeven_venda = investimento_total / max((1.0 - taxa_venda), 1e-9)

    return {
        "compra": float(compra),
        "area_m2": float(area_m2),
        "venda_m2": float(venda_m2),
        "venda_bruta": float(venda_bruta),
        "venda_prudente": float(venda_prudente),
        "obra_base": float(obra_base),
        "obra_total": float(obra_total),
        "aquisicao": float(aquisicao),
        "holding": float(holding),
        "investimento_total": float(investimento_total),
        "venda_fee": float(venda_fee),
        "lucro_liquido": float(lucro_liquido),
        "margem_liquida": float(margem_liquida),
        "roi": float(roi),
        "breakeven_venda": float(breakeven_venda),
    }

def calc_optimal_purchase_price(
    venda_prudente: float,
    obra_total: float,
    taxa_aquisicao: float,
    taxa_holding: float,
    taxa_venda: float,
    margem_alvo: float,
) -> float:
    """
    Closed-form solution for max purchase price P such that:
      lucro_liquido >= margem_alvo * venda_prudente

    lucro_liquido = V - [(P + P*a + W + (P+W)*h) + V*s]
    => P*(1+a+h) <= V*(1 - s - m) - W*(1+h)
    """
    V = float(venda_prudente)
    W = float(obra_total)
    a = float(taxa_aquisicao)
    h = float(taxa_holding)
    s = float(taxa_venda)
    m = float(margem_alvo)

    denom = (1.0 + a + h)
    rhs = V * (1.0 - s - m) - W * (1.0 + h)
    P = rhs / denom if denom > 0 else 0.0
    return max(0.0, P)

def stress_test_cases(bc: Dict[str, float], abs_meses: float) -> List[Dict[str, float]]:
    """
    Returns a list of stress scenarios with lucro and margem outputs.
    1) Venda -5% adicional
    2) Obra +10% adicional
    3) Atraso +3 meses (holding scaled by (meses+3)/meses)
    """
    base_V = bc["venda_prudente"]
    base_W = bc["obra_total"]
    base_P = bc["compra"]
    base_aq = bc["aquisicao"]
    base_hold = bc["holding"]
    base_fee = bc["venda_fee"]
    base_inv = bc["investimento_total"]
    taxa_venda = base_fee / base_V if base_V > 0 else 0.0
    taxa_aquisicao = base_aq / base_P if base_P > 0 else 0.0

    # Derive holding rate approx to reapply
    denom_hw = (base_P + base_W)
    taxa_holding = base_hold / denom_hw if denom_hw > 0 else 0.0

    meses = abs_meses if (abs_meses and abs_meses > 0) else 6.0

    def recompute(V: float, W: float, meses_scale: float = 1.0) -> Dict[str, float]:
        aq = base_P * taxa_aquisicao
        hold = (base_P + W) * taxa_holding * meses_scale
        inv = base_P + aq + W + hold
        fee = V * taxa_venda
        lucro = V - (inv + fee)
        margem = lucro / V if V > 0 else float("nan")
        return {"lucro": float(lucro), "margem": float(margem)}

    out = []
    # Base (for reference)
    base = recompute(base_V, base_W, 1.0)
    out.append({"nome": "Base", **base})

    # Venda -5%
    s1 = recompute(base_V * 0.95, base_W, 1.0)
    out.append({"nome": "Venda -5%", **s1})

    # Obra +10%
    s2 = recompute(base_V, base_W * 1.10, 1.0)
    out.append({"nome": "Obra +10%", **s2})

    # Atraso +3 meses
    scale = (meses + 3.0) / meses if meses > 0 else 1.5
    s3 = recompute(base_V, base_W, scale)
    out.append({"nome": "Atraso +3 meses", **s3})

    return out

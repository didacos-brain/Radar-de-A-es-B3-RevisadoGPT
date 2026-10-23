from __future__ import annotations

import io
import math
import warnings
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURAÇÃO PADRÃO — mantida a lógica do script original
# =============================================================================
CAPITAL_PADRAO = 50_000.00
ACOES_POR_METODOLOGIA_PADRAO = 2
QTD_ACOES_POR_LISTA_PADRAO = 10
LIQUIDEZ_MIN_PADRAO = 100_000.00
PREGOES_ZOOM_GRAFICO = 126  # aproximadamente 6 meses de pregões

METODOLOGIAS = {
    "EV/EBIT abaixo de 6": lambda df: df[(df["EV/EBIT"] > 0) & (df["EV/EBIT"] < 6.0)].sort_values("EV/EBIT", ascending=True),
    "P/VP abaixo de 0,60": lambda df: df[(df["P/VP"] > 0) & (df["P/VP"] < 0.60)].sort_values("P/VP", ascending=True),
    "Dividend Yield acima de 5%": lambda df: df[df["Div.Yield"] > 0.05].sort_values("Div.Yield", ascending=False),
    "PSR abaixo de 0,30": lambda df: df[(df["PSR"] > 0) & (df["PSR"] < 0.30)].sort_values("PSR", ascending=True),
    "P/L abaixo de 4": lambda df: df[(df["P/L"] > 0) & (df["P/L"] < 4.0)].sort_values("P/L", ascending=True),
}

st.set_page_config(
    page_title="Radar de Ações B3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
      h1, h2, h3 { letter-spacing: -0.025em; }
      div[data-testid="stMetric"] { background: rgba(128,128,128,0.07); padding: .7rem .85rem; border-radius: 12px; }
      div[data-testid="stDataFrame"] { border-radius: 10px; }
      .subtle { color: #8994a5; font-size: .88rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📈 Radar de Ações B3")
st.caption("Triagem fundamentalista configurável, confirmação de tendência, qualidade financeira e comparação de desempenho.")
st.info(
    "Ferramenta de triagem baseada nas regras configuradas. Os resultados dependem da disponibilidade e da qualidade dos dados externos e não constituem recomendação personalizada de investimento."
)


def converter_numero_br(serie: pd.Series) -> pd.Series:
    """Converte números em formato brasileiro; percentuais com '%' viram frações."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").astype(float)

    def converter(valor: Any) -> float:
        if pd.isna(valor):
            return float("nan")
        texto = str(valor).strip().replace("\xa0", "")
        if texto in {"", "-", "--", "N/A", "None"}:
            return float("nan")
        percentual = "%" in texto
        texto = texto.replace("%", "").replace(".", "").replace(",", ".")
        try:
            numero = float(texto)
            return numero / 100 if percentual else numero
        except ValueError:
            return float("nan")

    return serie.map(converter).astype(float)


@st.cache_data(ttl=1800, show_spinner=False)
def obter_dados_fundamentus() -> pd.DataFrame:
    url = "https://www.fundamentus.com.br/resultado.php"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    resposta = requests.get(url, headers=headers, timeout=30)
    resposta.raise_for_status()
    tabelas = pd.read_html(io.StringIO(resposta.text), decimal=",", thousands=".")
    if not tabelas:
        raise ValueError("O site não retornou uma tabela de ações.")

    df = tabelas[0].copy()
    colunas_obrigatorias = [
        "Papel", "Cotação", "P/L", "P/VP", "PSR", "Div.Yield", "EV/EBIT", "Liq.2meses"
    ]
    ausentes = [coluna for coluna in colunas_obrigatorias if coluna not in df.columns]
    if ausentes:
        raise ValueError("O formato retornado pelo Fundamentus mudou. Colunas ausentes: " + ", ".join(ausentes))

    colunas_numericas = [
        "Cotação", "P/L", "P/VP", "PSR", "Div.Yield", "EV/EBIT", "EV/EBITDA",
        "Mrg Ebit", "Mrg. Líq.", "ROIC", "ROE", "Liq.2meses", "Patrim. Líq",
        "Dív.Líq/ Patrim.", "Cresc. Rec.5a", "Liq. Corr.",
    ]
    for coluna in colunas_numericas:
        if coluna in df.columns:
            df[coluna] = converter_numero_br(df[coluna])
        else:
            # Métricas opcionais podem mudar de nome ou desaparecer da fonte.
            df[coluna] = float("nan")

    df["Papel"] = df["Papel"].astype(str).str.strip().str.upper()
    # Não restringir a letras antes do código numérico: alguns tickers válidos, como B3SA3,
    # contêm números também no radical. A tabela do Fundamentus já separa os ativos.
    df = df[df["Papel"].str.len().between(5, 6)].copy()
    return df


@st.cache_data(ttl=21600, show_spinner=False)
def obter_historico(papel: str) -> tuple[pd.DataFrame, str | None]:
    """Busca até dois anos de cotações; o cache evita consultar o mesmo ativo repetidamente."""
    try:
        dados = yf.Ticker(f"{papel}.SA").history(period="2y", auto_adjust=False)
        if dados is None or dados.empty:
            return pd.DataFrame(), "O provedor não retornou histórico para este ativo."
        dados = dados.copy()
        if isinstance(dados.columns, pd.MultiIndex):
            dados.columns = dados.columns.get_level_values(0)
        necessarias = {"Close", "Open", "Volume"}
        if not necessarias.issubset(set(dados.columns)):
            return pd.DataFrame(), "O histórico não contém todas as colunas esperadas."
        dados = dados.dropna(subset=["Close"])
        return dados, None
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def obter_metricas_e_historico(papel: str, gatilho_sma_pct: float = 10.0) -> dict[str, Any]:
    dados, erro = obter_historico(papel)
    if dados.empty or len(dados) < 200:
        mensagem = "SEM DADOS (menos de 200 pregões)" if not erro else f"ERRO NA CONSULTA: {erro}"
        return {
            "aprovada_sma": False,
            "Preco_YF": None,
            "SMA_200": None,
            "Gatilho_SMA": None,
            "gatilho_sma_pct": gatilho_sma_pct,
            "Dist_SMA200_%": None,
            "Limite_2%_Vol_R$": None,
            "Status_Tecnico": mensagem,
            "historico": None,
        }

    # Close é ajustado por desdobramentos pelo Yahoo, mas não por proventos.
    # Assim, a SMA técnica não mistura dividendos à série de preços.
    dados["SMA200"] = dados["Close"].rolling(window=200).mean()
    dados["Gatilho_SMA"] = dados["SMA200"] * (1.0 + gatilho_sma_pct / 100.0)
    dados["Vol_MA60"] = dados["Volume"].rolling(window=60).mean()
    dados["VolumeFinanceiro"] = dados["Close"] * dados["Volume"]
    dados["VolFinanceiro_MA60"] = dados["VolumeFinanceiro"].rolling(window=60).mean()

    preco_atual = float(dados["Close"].iloc[-1])
    sma_200 = float(dados["SMA200"].iloc[-1])
    gatilho = float(dados["Gatilho_SMA"].iloc[-1])
    if not math.isfinite(sma_200) or sma_200 == 0:
        return {
            "aprovada_sma": False, "Preco_YF": round(preco_atual, 2), "SMA_200": None,
            "Gatilho_SMA": None, "gatilho_sma_pct": gatilho_sma_pct,
            "Dist_SMA200_%": None, "Limite_2%_Vol_R$": None,
            "Status_Tecnico": "SEM DADOS PARA CALCULAR SMA200", "historico": dados,
        }

    dist_pct = ((preco_atual / sma_200) - 1.0) * 100.0
    vol_financeiro_medio_60d = float(dados["VolFinanceiro_MA60"].iloc[-1])
    limite_2pct = vol_financeiro_medio_60d * 0.02 if math.isfinite(vol_financeiro_medio_60d) else 0.0
    aprovada_sma = preco_atual >= gatilho

    if aprovada_sma:
        status = f"TENDÊNCIA CONFIRMADA (preço ≥ SMA200 + {gatilho_sma_pct:g}%)"
    elif preco_atual >= sma_200:
        status = f"ACIMA DA SMA200, mas abaixo do gatilho +{gatilho_sma_pct:g}%"
    else:
        status = "ABAIXO DA SMA200"

    return {
        "aprovada_sma": aprovada_sma,
        "Preco_YF": round(preco_atual, 2),
        "SMA_200": round(sma_200, 2),
        "Gatilho_SMA": round(gatilho, 2),
        "gatilho_sma_pct": gatilho_sma_pct,
        "Dist_SMA200_%": round(dist_pct, 2),
        "Limite_2%_Vol_R$": round(limite_2pct, 2),
        "Status_Tecnico": status,
        "historico": dados,
    }


def aplicar_peneira_basica(
    df: pd.DataFrame,
    liquidez_minima: float,
    aplicar_filtro_roe: bool = True,
    roe_minimo_pct: float = 5.0,
    aplicar_filtro_roic: bool = False,
    roic_minimo_pct: float = 5.0,
    exigir_margem_ebit_positiva: bool = False,
    limitar_divida: bool = False,
    divida_liquida_patrimonio_max: float = 1.5,
) -> tuple[pd.DataFrame, list[str]]:
    """Aplica filtros gerais e critérios opcionais de qualidade/solidez.

    ROE é a condição de qualidade padrão. ROIC, margem EBIT e dívida líquida/PL
    ficam configuráveis porque a interpretação varia bastante entre setores,
    especialmente instituições financeiras.
    """
    filtros = (df["P/L"] > 0) & (df["Liq.2meses"] >= liquidez_minima)
    avisos: list[str] = []

    def aplicar_coluna(coluna: str, condicao: pd.Series, descricao: str) -> None:
        nonlocal filtros
        if coluna not in df.columns or df[coluna].notna().sum() == 0:
            avisos.append(f"O filtro {descricao} não foi aplicado: a fonte não forneceu dados válidos em '{coluna}'.")
            return
        filtros = filtros & condicao.fillna(False)

    if aplicar_filtro_roe:
        aplicar_coluna("ROE", df["ROE"] >= roe_minimo_pct / 100.0, f"ROE ≥ {roe_minimo_pct:g}%")
    if aplicar_filtro_roic:
        aplicar_coluna("ROIC", df["ROIC"] >= roic_minimo_pct / 100.0, f"ROIC ≥ {roic_minimo_pct:g}%")
    if exigir_margem_ebit_positiva:
        aplicar_coluna("Mrg Ebit", df["Mrg Ebit"] > 0, "margem EBIT positiva")
    if limitar_divida:
        aplicar_coluna(
            "Dív.Líq/ Patrim.",
            df["Dív.Líq/ Patrim."] <= divida_liquida_patrimonio_max,
            f"dívida líquida/PL ≤ {divida_liquida_patrimonio_max:g}",
        )

    filtrado = df[filtros].copy()
    filtrado["Radical"] = filtrado["Papel"].str[:4]
    filtrado = (
        filtrado.sort_values("Liq.2meses", ascending=False)
        .drop_duplicates(subset=["Radical"], keep="first")
        .copy()
    )
    return filtrado, avisos


def executar_analise(
    capital_total: float,
    acoes_por_metodologia: int,
    qtd_acoes_por_lista: int,
    liquidez_minima: float,
    gatilho_sma_pct: float,
    aplicar_filtro_roe: bool,
    roe_minimo_pct: float,
    aplicar_filtro_roic: bool,
    roic_minimo_pct: float,
    exigir_margem_ebit_positiva: bool,
    limitar_divida: bool,
    divida_liquida_patrimonio_max: float,
    progress_callback=None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, dict[str, Any]], int, list[str]]:
    bruto = obter_dados_fundamentus()
    df, avisos_filtros = aplicar_peneira_basica(
        bruto, liquidez_minima, aplicar_filtro_roe, roe_minimo_pct,
        aplicar_filtro_roic, roic_minimo_pct, exigir_margem_ebit_positiva,
        limitar_divida, divida_liquida_patrimonio_max,
    )
    rankings = {nome: funcao(df) for nome, funcao in METODOLOGIAS.items()}

    # Monta uma fila sem duplicar consultas históricas para o mesmo ticker.
    candidatos_por_metodo = {nome: rank.head(qtd_acoes_por_lista) for nome, rank in rankings.items()}
    papeis_unicos: list[str] = []
    for tabela in candidatos_por_metodo.values():
        for papel in tabela["Papel"].astype(str).tolist():
            if papel not in papeis_unicos:
                papeis_unicos.append(papel)

    metricas: dict[str, dict[str, Any]] = {}
    for idx, papel in enumerate(papeis_unicos, start=1):
        metricas[papel] = obter_metricas_e_historico(papel, gatilho_sma_pct)
        if progress_callback:
            progress_callback(idx, len(papeis_unicos), papel)

    total_slots = len(METODOLOGIAS) * acoes_por_metodologia
    aporte_por_slot = capital_total / total_slots if total_slots else 0
    carteira: list[dict[str, Any]] = []
    acoes_selecionadas: list[dict[str, Any]] = []
    radicais_alocados: set[str] = set()
    slot_num = 1
    tabelas_top: dict[str, pd.DataFrame] = {}

    for nome_met, df_met in candidatos_por_metodo.items():
        linhas_met: list[dict[str, Any]] = []
        escolhidas_na_met = 0
        for pos, (_, row) in enumerate(df_met.iterrows(), start=1):
            papel = str(row["Papel"])
            radical = papel[:4]
            graf = metricas.get(papel) or obter_metricas_e_historico(papel, gatilho_sma_pct)
            dist = graf["Dist_SMA200_%"]
            limite_volume = graf["Limite_2%_Vol_R$"] or 0
            linhas_met.append({
                "Rank": f"{pos}º",
                "Papel": papel,
                "Cotação Fundamentus (R$)": round(float(row["Cotação"]), 2) if pd.notna(row["Cotação"]) else None,
                "EV/EBIT": round(float(row["EV/EBIT"]), 2) if pd.notna(row["EV/EBIT"]) else None,
                "P/VP": round(float(row["P/VP"]), 2) if pd.notna(row["P/VP"]) else None,
                "Dividend Yield (%)": round(float(row["Div.Yield"]) * 100, 2) if pd.notna(row["Div.Yield"]) else None,
                "PSR": round(float(row["PSR"]), 2) if pd.notna(row["PSR"]) else None,
                "P/L": round(float(row["P/L"]), 2) if pd.notna(row["P/L"]) else None,
                "ROE (%)": round(float(row["ROE"]) * 100, 2) if pd.notna(row["ROE"]) else None,
                "ROIC (%)": round(float(row["ROIC"]) * 100, 2) if pd.notna(row["ROIC"]) else None,
                "Margem EBIT (%)": round(float(row["Mrg Ebit"]) * 100, 2) if pd.notna(row["Mrg Ebit"]) else None,
                "Margem líquida (%)": round(float(row["Mrg. Líq."]) * 100, 2) if pd.notna(row["Mrg. Líq."]) else None,
                "Dívida líquida/PL": round(float(row["Dív.Líq/ Patrim."]), 2) if pd.notna(row["Dív.Líq/ Patrim."]) else None,
                "Crescimento receita 5a (%)": round(float(row["Cresc. Rec.5a"]) * 100, 2) if pd.notna(row["Cresc. Rec.5a"]) else None,
                "Liquidez 2 meses (R$)": float(row["Liq.2meses"]) if pd.notna(row["Liq.2meses"]) else None,
                "SMA 200 (R$)": graf["SMA_200"],
                f"Gatilho +{gatilho_sma_pct:g}% (R$)": graf["Gatilho_SMA"],
                "Distância da SMA200 (%)": dist,
                "Limite estimado 2% do financeiro diário (R$)": graf["Limite_2%_Vol_R$"],
                "Status técnico": graf["Status_Tecnico"],
            })

            if (
                escolhidas_na_met < acoes_por_metodologia
                and graf["aprovada_sma"]
                and limite_volume >= aporte_por_slot
                and radical not in radicais_alocados
            ):
                radicais_alocados.add(radical)
                escolhidas_na_met += 1
                item = {
                    "Vaga": f"Vaga {slot_num:02d}",
                    "Metodologia": nome_met,
                    "Ativo escolhido": papel,
                    "Posição no ranking": f"{pos}º",
                    "Cotação (R$)": graf["Preco_YF"],
                    "Aporte teórico da vaga (R$)": round(aporte_por_slot, 2),
                    "Distância da SMA200 (%)": f"{dist:+.2f}%" if dist is not None else "—",
                    "EV/EBIT": round(float(row["EV/EBIT"]), 2) if pd.notna(row["EV/EBIT"]) else None,
                    "P/VP": round(float(row["P/VP"]), 2) if pd.notna(row["P/VP"]) else None,
                    "Dividend Yield (%)": round(float(row["Div.Yield"]) * 100, 2) if pd.notna(row["Div.Yield"]) else None,
                    "PSR": round(float(row["PSR"]), 2) if pd.notna(row["PSR"]) else None,
                    "P/L": round(float(row["P/L"]), 2) if pd.notna(row["P/L"]) else None,
                    "ROE (%)": round(float(row["ROE"]) * 100, 2) if pd.notna(row["ROE"]) else None,
                    "ROIC (%)": round(float(row["ROIC"]) * 100, 2) if pd.notna(row["ROIC"]) else None,
                    "Margem EBIT (%)": round(float(row["Mrg Ebit"]) * 100, 2) if pd.notna(row["Mrg Ebit"]) else None,
                    "Dívida líquida/PL": round(float(row["Dív.Líq/ Patrim."]), 2) if pd.notna(row["Dív.Líq/ Patrim."]) else None,
                    "Status": "Candidata elegível para análise; não é ordem de compra",
                }
                carteira.append(item)
                acoes_selecionadas.append({
                    "Vaga": item["Vaga"],
                    "Metodologia": nome_met,
                    "Ativo escolhido": papel,
                    "Distância da SMA200 (%)": item["Distância da SMA200 (%)"],
                })
                slot_num += 1

        while escolhidas_na_met < acoes_por_metodologia:
            carteira.append({
                "Vaga": f"Vaga {slot_num:02d}",
                "Metodologia": nome_met,
                "Ativo escolhido": "Vaga não preenchida — avaliar separadamente",
                "Posição no ranking": "—",
                "Cotação (R$)": None,
                "Aporte teórico da vaga (R$)": round(aporte_por_slot, 2),
                "Distância da SMA200 (%)": "—",
                "EV/EBIT": None,
                "P/VP": None,
                "Dividend Yield (%)": None,
                "PSR": None,
                "P/L": None,
                "ROE (%)": None,
                "ROIC (%)": None,
                "Margem EBIT (%)": None,
                "Dívida líquida/PL": None,
                "Status": "Nenhuma ação aprovada; não aloca automaticamente em renda fixa",
            })
            escolhidas_na_met += 1
            slot_num += 1
        tabelas_top[nome_met] = pd.DataFrame(linhas_met)

    df_carteira = pd.DataFrame(carteira)
    return tabelas_top, df_carteira, metricas, len(df), avisos_filtros


def grafico_tecnico(papel: str, info: dict[str, Any]) -> go.Figure | None:
    dados = info.get("historico")
    if dados is None or dados.empty:
        return None
    zoom = dados.tail(PREGOES_ZOOM_GRAFICO).copy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Close"], mode="lines", name="Cotação", line=dict(color="#38BDF8", width=2.4)))
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["SMA200"], mode="lines", name="SMA 200", line=dict(color="#F59E0B", width=1.8)))
    gatilho_pct = info.get("gatilho_sma_pct", 10.0)
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Gatilho_SMA"], mode="lines", name=f"Gatilho +{gatilho_pct:g}%", line=dict(color="#10B981", width=1.6, dash="dash")))
    fig.update_layout(
        title=f"{papel} · Cotação, SMA 200 e gatilho +{gatilho_pct:g}%",
        height=360,
        margin=dict(l=8, r=8, t=55, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Preço (R$)",
        hovermode="x unified",
    )
    return fig


def grafico_volume(papel: str, info: dict[str, Any]) -> go.Figure | None:
    dados = info.get("historico")
    if dados is None or dados.empty:
        return None
    zoom = dados.tail(PREGOES_ZOOM_GRAFICO).copy()
    cores = ["#10B981" if c >= o else "#EF4444" for c, o in zip(zoom["Close"], zoom["Open"])]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=zoom.index, y=zoom["Volume"] / 1000, name="Volume (mil ações)", marker_color=cores, opacity=0.65))
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Vol_MA60"] / 1000, mode="lines", name="Média de 60 pregões", line=dict(color="#FACC15", width=2)))
    fig.update_layout(
        title=f"{papel} · Volume negociado",
        height=260,
        margin=dict(l=8, r=8, t=45, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Mil ações",
        hovermode="x unified",
    )
    return fig


def grafico_comparativo(papeis: list[str], metricas: dict[str, dict[str, Any]]) -> go.Figure | None:
    fig = go.Figure()
    algum = False
    for papel in papeis:
        info = metricas.get(papel, {})
        dados = info.get("historico")
        if dados is None or dados.empty:
            continue
        zoom = dados.tail(PREGOES_ZOOM_GRAFICO)
        coluna_retorno = "Adj Close" if "Adj Close" in zoom.columns else "Close"
        precos_retorno = zoom[coluna_retorno].dropna()
        if precos_retorno.empty or precos_retorno.iloc[0] == 0:
            continue
        serie = (precos_retorno / precos_retorno.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(x=serie.index, y=serie, mode="lines", name=papel, line=dict(width=2)))
        algum = True

    try:
        ibov = yf.Ticker("^BVSP").history(period="1y", auto_adjust=False).tail(PREGOES_ZOOM_GRAFICO)
        if not ibov.empty:
            coluna_ibov = "Adj Close" if "Adj Close" in ibov.columns else "Close"
            precos_ibov = ibov[coluna_ibov].dropna()
            if not precos_ibov.empty and precos_ibov.iloc[0] != 0:
                serie_ibov = (precos_ibov / precos_ibov.iloc[0] - 1) * 100
                fig.add_trace(go.Scatter(x=serie_ibov.index, y=serie_ibov, mode="lines", name="Ibovespa", line=dict(color="#64748B", dash="dash", width=2.5)))
            algum = True
    except Exception:
        pass

    if not algum:
        return None
    fig.add_hline(y=0, line_dash="dot", line_color="#64748B")
    fig.update_layout(
        title="Desempenho relativo nos últimos ~6 meses (ações com ajuste de proventos quando disponível)",
        height=420,
        margin=dict(l=8, r=8, t=55, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Variação (%)",
        hovermode="x unified",
    )
    return fig


# =============================================================================
# INTERFACE
# =============================================================================
with st.sidebar:
    st.header("⚙️ Parâmetros da análise")
    capital_total = st.number_input("Capital total da carteira (R$)", min_value=100.0, value=CAPITAL_PADRAO, step=1000.0)
    acoes_por_metodologia = st.number_input("Vagas por metodologia", min_value=1, max_value=5, value=ACOES_POR_METODOLOGIA_PADRAO, step=1)
    qtd_acoes_por_lista = st.slider("Candidatas analisadas por metodologia", min_value=3, max_value=10, value=QTD_ACOES_POR_LISTA_PADRAO)
    liquidez_minima = st.number_input("Liquidez mínima em 2 meses (R$)", min_value=0.0, value=LIQUIDEZ_MIN_PADRAO, step=25000.0)
    gatilho_sma_pct = st.slider("Gatilho acima da SMA200 (%)", min_value=0, max_value=20, value=10, step=5,
                                help="Ex.: 0% exige preço acima da SMA200; 5% ou 10% exige uma tendência mais forte.")
    st.subheader("Qualidade e saúde financeira")
    aplicar_filtro_roe = st.checkbox("Exigir ROE mínimo", value=True, help="Filtro geral de rentabilidade do patrimônio; confira sua adequação para o setor.")
    roe_minimo_pct = st.number_input("ROE mínimo (%)", min_value=-100.0, max_value=100.0, value=5.0, step=1.0, disabled=not aplicar_filtro_roe)
    aplicar_filtro_roic = st.checkbox("Exigir ROIC mínimo", value=False, help="ROIC pode não ser comparável em todos os setores, especialmente instituições financeiras.")
    roic_minimo_pct = st.number_input("ROIC mínimo (%)", min_value=-100.0, max_value=100.0, value=5.0, step=1.0, disabled=not aplicar_filtro_roic)
    exigir_margem_ebit_positiva = st.checkbox("Exigir margem EBIT positiva", value=False, help="Filtro mais adequado a empresas operacionais; não é universal para bancos e seguradoras.")
    limitar_divida = st.checkbox("Limitar dívida líquida/ patrimônio", value=False, help="A interpretação depende do setor e de patrimônios líquidos positivos.")
    divida_liquida_patrimonio_max = st.number_input("Dívida líquida/PL máxima", min_value=-10.0, max_value=20.0, value=1.5, step=0.25, disabled=not limitar_divida)
    forcar_atualizacao = st.checkbox("Forçar nova coleta dos dados", value=False, help="Limpa o cache antes de consultar novamente o Fundamentus e os históricos.")
    st.caption("A análise técnica exige, por padrão, ao menos 200 pregões de histórico. Os filtros por setor devem ser interpretados com cautela.")

executar = st.button("🔎 Executar análise", type="primary", use_container_width=True)
if executar:
    if forcar_atualizacao:
        st.cache_data.clear()
    barra = st.progress(0, text="Conectando ao Fundamentus...")
    def atualizar_progresso(atual: int, total: int, papel: str) -> None:
        percentagem = int(atual / total * 100) if total else 100
        barra.progress(percentagem, text=f"Analisando histórico de {papel} ({atual}/{total})...")

    try:
        with st.spinner("Coletando fundamentos e calculando os filtros técnicos. A primeira consulta pode demorar."):
            tabelas_top, df_carteira, metricas, qtd_filtradas, avisos_filtros = executar_analise(
                float(capital_total),
                int(acoes_por_metodologia),
                int(qtd_acoes_por_lista),
                float(liquidez_minima),
                float(gatilho_sma_pct),
                bool(aplicar_filtro_roe),
                float(roe_minimo_pct),
                bool(aplicar_filtro_roic),
                float(roic_minimo_pct),
                bool(exigir_margem_ebit_positiva),
                bool(limitar_divida),
                float(divida_liquida_patrimonio_max),
                progress_callback=atualizar_progresso,
            )
        st.session_state["analise"] = {
            "tabelas_top": tabelas_top,
            "carteira": df_carteira,
            "metricas": metricas,
            "qtd_filtradas": qtd_filtradas,
            "avisos_filtros": avisos_filtros,
            "config_filtros": {
                "gatilho_sma_pct": float(gatilho_sma_pct),
                "aplicar_filtro_roe": bool(aplicar_filtro_roe),
                "roe_minimo_pct": float(roe_minimo_pct),
                "aplicar_filtro_roic": bool(aplicar_filtro_roic),
                "roic_minimo_pct": float(roic_minimo_pct),
                "exigir_margem_ebit_positiva": bool(exigir_margem_ebit_positiva),
                "limitar_divida": bool(limitar_divida),
                "divida_liquida_patrimonio_max": float(divida_liquida_patrimonio_max),
            },
            "capital_total": float(capital_total),
            "acoes_por_metodologia": int(acoes_por_metodologia),
            "aporte_por_slot": float(capital_total) / (len(METODOLOGIAS) * int(acoes_por_metodologia)),
            "executado_em": datetime.now().strftime("%d/%m/%Y às %H:%M"),
        }
        barra.progress(100, text="Análise concluída.")
    except Exception as exc:
        barra.empty()
        st.error(f"Não foi possível concluir a análise: {exc}")
        st.markdown("Confira sua conexão e tente novamente mais tarde. O Fundamentus ou o Yahoo Finance podem estar temporariamente indisponíveis ou limitar consultas automatizadas.")

analise = st.session_state.get("analise")
if not analise:
    st.markdown("### Como usar")
    st.markdown(
        "1. Abra **Parâmetros da análise** para ajustar o capital e os filtros.\n"
        "2. Toque em **Executar análise**.\n"
        "3. Navegue pelos rankings, pela carteira-modelo e pelos gráficos interativos."
    )
    st.caption("Dados consultados no Fundamentus e no Yahoo Finance. A disponibilidade dos serviços externos não é garantida.")
else:
    df_carteira = analise["carteira"]
    metricas = analise["metricas"]
    selecionadas = df_carteira.loc[
        df_carteira["Ativo escolhido"].notna()
        & ~df_carteira["Ativo escolhido"].astype(str).str.startswith("Vaga não preenchida"),
        "Ativo escolhido",
    ].astype(str).tolist()
    aporte_por_slot = analise["aporte_por_slot"]

    st.caption(f"Última execução: {analise['executado_em']} · {analise['qtd_filtradas']} ações passaram pelos filtros fundamentalistas configurados.")
    for aviso in analise.get("avisos_filtros", []):
        st.warning(aviso)
    c1, c2, c3 = st.columns(3)
    c1.metric("Capital configurado", f"R$ {analise['capital_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Aporte teórico por vaga", f"R$ {aporte_por_slot:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Ativos selecionados", f"{len(selecionadas)} de {len(df_carteira)} vagas")

    tab_carteira, tab_rankings, tab_graficos, tab_regras = st.tabs(["📋 Carteira-modelo", "🔍 Rankings", "📊 Gráficos", "ℹ️ Regras"])

    with tab_carteira:
        st.subheader("Distribuição sugerida pelas regras do sistema")
        st.dataframe(df_carteira, use_container_width=True, hide_index=True)
        csv_carteira = df_carteira.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Baixar carteira em CSV", data=csv_carteira, file_name="carteira_modelo_b3.csv", mime="text/csv", use_container_width=True)
        st.caption("O aporte por vaga é apenas uma referência matemática. Vagas vazias não são alocadas automaticamente em ações ou títulos. A tabela indica candidatas elegíveis, não ordens de compra.")

    with tab_rankings:
        st.subheader("Candidatas por metodologia")
        metodologia_escolhida = st.selectbox("Escolha a metodologia", list(analise["tabelas_top"].keys()))
        df_rank = analise["tabelas_top"][metodologia_escolhida]
        if df_rank.empty:
            st.warning("Nenhuma ação passou pelos critérios fundamentalistas desta metodologia.")
        else:
            st.dataframe(df_rank, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar este ranking em CSV",
                data=df_rank.to_csv(index=False).encode("utf-8-sig"),
                file_name="ranking_" + metodologia_escolhida.lower().replace(" ", "_").replace("/", "-") + ".csv",
                mime="text/csv",
                use_container_width=True,
                key="download_ranking",
            )

    with tab_graficos:
        st.subheader("Análise técnica das candidatas consultadas")
        papeis_com_historico = [p for p, info in metricas.items() if info.get("historico") is not None]
        if papeis_com_historico:
            papel_grafico = st.selectbox("Escolha uma ação candidata para inspeção", papeis_com_historico)
            info = metricas[papel_grafico]
            k1, k2, k3 = st.columns(3)
            k1.metric("Cotação", f"R$ {info['Preco_YF']:.2f}" if info["Preco_YF"] is not None else "—")
            k2.metric("SMA 200", f"R$ {info['SMA_200']:.2f}" if info["SMA_200"] is not None else "—")
            k3.metric("Distância da SMA 200", f"{info['Dist_SMA200_%']:+.2f}%" if info["Dist_SMA200_%"] is not None else "—")
            st.write("**Status técnico:** " + str(info["Status_Tecnico"]))
            fig_preco = grafico_tecnico(papel_grafico, info)
            fig_volume = grafico_volume(papel_grafico, info)
            if fig_preco is not None:
                st.plotly_chart(fig_preco, use_container_width=True, config={"displayModeBar": False})
            if fig_volume is not None:
                st.plotly_chart(fig_volume, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Nenhuma ação selecionada tem histórico suficiente para exibir gráficos técnicos.")

        st.divider()
        st.subheader("Comparativo de desempenho das ações selecionadas")
        papeis_selecionados_com_historico = [p for p in selecionadas if p in metricas and metricas[p].get("historico") is not None]
        if papeis_selecionados_com_historico:
            if st.button("Gerar comparativo com Ibovespa", use_container_width=True):
                with st.spinner("Consultando o histórico do Ibovespa..."):
                    fig_comp = grafico_comparativo(papeis_selecionados_com_historico, metricas)
                if fig_comp:
                    st.session_state["grafico_comparativo"] = fig_comp
                else:
                    st.warning("Não foi possível gerar o comparativo com os dados disponíveis.")
            if st.session_state.get("grafico_comparativo"):
                st.plotly_chart(st.session_state["grafico_comparativo"], use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("O comparativo ficará disponível quando houver ativos selecionados com histórico válido.")

    with tab_regras:
        st.subheader("Critérios aplicados")
        st.markdown(
            "- **Peneira básica:** P/L positivo, liquidez mínima configurada e manutenção do papel mais líquido por radical de quatro letras.\n"
            "- **EV/EBIT:** maior que zero e menor que 6.\n"
            "- **P/VP:** maior que zero e menor que 0,60.\n"
            "- **Dividend Yield:** acima de 5%.\n"
            "- **PSR:** maior que zero e menor que 0,30.\n"
            "- **P/L:** maior que zero e menor que 4.\n"
            f"- **Confirmação técnica:** cotação igual ou superior à SMA200 + {analise['config_filtros']['gatilho_sma_pct']:g}%.\n"
            "- **Qualidade:** ROE mínimo configurável; ROIC, margem EBIT e dívida líquida/PL são filtros opcionais, pois a interpretação varia por setor.\n"
            "- **Filtro de volume:** limite de 2% da média do valor financeiro diário negociado nos últimos 60 pregões (preço × volume).\n"
            "- **Diversificação entre métodos:** evita alocar mais de um papel com o mesmo radical de quatro letras; isso não garante diversificação por setor.\n"
            "- **Vagas vazias:** não são preenchidas automaticamente com renda fixa.\n\n"
            "### Limitações importantes\n"
            "- Os fundamentos do Fundamentus são atuais, e não um histórico de informações disponíveis em cada data passada. Os gráficos, portanto, não constituem um backtest válido da estratégia.\n"
            "- Ainda não há simulação da carteira com rebalanceamentos históricos, custos, impostos, slippage e fundamentos históricos ponto a ponto.\n"
            "- A lista é uma triagem de candidatas, não uma ordem de compra nem uma garantia de retorno."
        )
        st.caption("Os critérios são regras do seu algoritmo, não uma garantia de desempenho futuro. Cotação, fundamentos e históricos podem apresentar atraso, inconsistência ou indisponibilidade.")

st.divider()
st.caption("Radar de Ações B3 · Interface web adaptável para celular · Fontes externas: Fundamentus e Yahoo Finance")

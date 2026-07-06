"""
Orquestrador do processo de cálculo de RV.

Fluxo:
  1. Normaliza e enriquece os dados de colaboradores com os indicadores.
  2. Para cada colaborador: verifica elegibilidade, calcula RV e aplica proporcionalidade.
  3. Retorna DataFrame com todos os resultados para geração de output e relatório.

Escopo por indicador:
  Atendentes       → NPS: unidade | DMA e Fat.: individual
  Atendentes Líderes/Gestores → NPS, DMA, Fat.: unidade
  Regionais        → NPS, DMA, Fat.: regional (consolidado das unidades)
  Líderes de Frota → NPS, Preventiva, NONREV: unidade
  Líderes de Pátio → NPS, NONREV, Bate Pátio: unidade
  Operadores Frota → NPS, Preventiva, NONREV: unidade
  Outros Cargos    → NPS: unidade
"""

import pandas as pd

from config import GRUPOS_MODELO_PERCENTUAL, GRUPOS_MODELO_TETO, TETOS, REGRAS
from rv.loader import normalizar_colaboradores
from rv.eligibility import is_elegivel, aplicar_proporcionalidade
from rv.calculators import calculadora


# Coluna do DataFrame de colaboradores correspondente a cada indicador de
# Regras_Calculo, para os indicadores vinculados diretamente à loja do
# colaborador (não agregados por regional).
# 'bate_patio' fica de fora por decisão do usuário: esse indicador pode
# assumir 0.0 quando ausente, sem cancelar o cálculo (rv/loader.py::_proc_bate_patio
# já faz esse fillna).
_COLUNA_POR_INDICADOR = {
    "nps":         "nps",
    "nonrev":      "nonrev_pct",
    "preventiva":  "preventiva_pct",
}


def _validar_indicadores_por_loja(colab: pd.DataFrame) -> None:
    """
    Garante que os arquivos de origem vieram completos: nenhum colaborador pode
    ficar sem NPS/NONREV/Preventiva quando seu grupo depende deles.
    'regional' fica de fora — seus indicadores vêm agregados por regional, não
    da loja do próprio colaborador. 'bate_patio' fica de fora por decisão do
    usuário (ver comentário em _COLUNA_POR_INDICADOR).
    Levanta ValueError (cancela o cálculo) em vez de assumir um valor padrão.
    """
    erros = []
    for grupo, indicadores in REGRAS.items():
        if grupo == "regional":
            continue
        subset = colab[colab["grupo"] == grupo]
        if subset.empty:
            continue
        for indicador in indicadores:
            coluna = _COLUNA_POR_INDICADOR.get(indicador)
            if coluna is None or coluna not in subset.columns:
                continue
            faltantes = subset[subset[coluna].isna()]
            if not faltantes.empty:
                lojas = sorted(faltantes["unidade"].unique())
                erros.append(f"  - '{indicador}' ausente para o grupo '{grupo}' nas lojas: {lojas}")

    if erros:
        raise ValueError(
            "Cálculo de RV cancelado — dados de entrada incompletos:\n"
            + "\n".join(erros)
            + "\n\nCorrija os arquivos de origem (loja sem dado) e rode o cálculo novamente."
        )


# ---------------------------------------------------------------------------
# Helpers de enriquecimento
# ---------------------------------------------------------------------------

def _merge_nps(colab: pd.DataFrame, nps_df: pd.DataFrame) -> pd.DataFrame:
    # nps_df já vem processado pelo loader (unidade + nps numérico)
    return colab.merge(nps_df[["unidade", "nps"]], on="unidade", how="left")


def _merge_coral(
    colab: pd.DataFrame,
    coral_df: pd.DataFrame,
    coral_por_loja_df: pd.DataFrame,
    meta_df: pd.DataFrame,
    mapeamento_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Vincula DMA e faturamento individual via mapeamento login Coral → matrícula.
    coral_df já vem do loader com: login_coral, dma, dma_valor, dma_dias,
    faturamento_realizado, unidade (todos numéricos).
    coral_por_loja_df: unidade, fat_realizado_loja — faturamento agregado pela
    loja do CONTRATO (coluna LOJA de cada linha do dma-accumulated), usado para
    Líderes/Gestores/Regionais. O faturamento individual do colaborador
    (faturamento_realizado, acima) continua somando por LOGIN, independente da
    loja de cada contrato.
    meta_df já vem do loader com: login_coral, meta_faturamento (numérico).
    mapeamento_df: login_coral → matricula.

    Importante: ao agregar DMA acima do nível de login (matrícula com múltiplos
    logins, unidade, regional), soma-se dma_valor e dma_dias separadamente e
    só então divide — nunca tira média dos DMAs já calculados por login, pois
    média de razões != razão das somas.
    """
    mapa = mapeamento_df[["login_coral", "matricula"]].copy()

    # Junta coral com mapeamento para obter matrícula
    coral = coral_df.merge(mapa, on="login_coral", how="left")

    # Junta meta com mapeamento (matrícula) e com coral (unidade por login)
    meta = meta_df.merge(mapa, on="login_coral", how="left")
    meta = meta.merge(coral_df[["login_coral", "unidade"]], on="login_coral", how="left")

    # Vincula indicadores individuais ao colaborador pela matrícula
    # Agrega por matrícula para evitar duplicação quando há múltiplos logins por pessoa
    ind = (
        coral[["matricula", "dma_valor", "dma_dias", "faturamento_realizado"]]
        .dropna(subset=["matricula"])
        .groupby("matricula", as_index=False)
        .agg(dma_valor=("dma_valor", "sum"), dma_dias=("dma_dias", "sum"),
             faturamento_realizado=("faturamento_realizado", "sum"))
    )
    ind["dma"] = (ind["dma_valor"] / ind["dma_dias"].replace(0, float("nan"))).fillna(0.0)
    ind = ind[["matricula", "dma", "faturamento_realizado"]]
    ind_meta = (
        meta[["matricula", "meta_faturamento"]]
        .dropna(subset=["matricula"])
        .groupby("matricula", as_index=False)
        .agg(meta_faturamento=("meta_faturamento", "sum"))
    )

    colab = colab.merge(ind, on="matricula", how="left")
    colab = colab.merge(ind_meta, on="matricula", how="left")
    colab[["dma", "faturamento_realizado", "meta_faturamento"]] = (
        colab[["dma", "faturamento_realizado", "meta_faturamento"]].fillna(0.0)
    )

    # Meta de loja/regional deve somar só a meta dos ATENDENTES daquela loja —
    # exclui logins cuja matrícula pertence a outro grupo (ex: o próprio
    # líder/gestor com uma entrada individual na planilha de meta). Logins sem
    # matrícula mapeada (fora da Lista de Logins) são mantidos, pois só
    # atendentes têm login no Coral.
    cargos = colab[["matricula", "grupo_calculo"]].drop_duplicates()
    meta_equipe = meta.merge(cargos, on="matricula", how="left")
    meta_equipe = meta_equipe[
        meta_equipe["grupo_calculo"].isna() | (meta_equipe["grupo_calculo"] == "atendente")
    ]

    # DMA por unidade (para Líderes e Gestores) — continua vinculado pela loja
    # "de casa" do login, já que o DMA é uma métrica de qualidade da venda, não
    # de faturamento por loja.
    unit_dma = coral.groupby("unidade", as_index=False).agg(
        dma_valor=("dma_valor", "sum"),
        dma_dias=("dma_dias", "sum"),
    )
    unit_dma["dma_unidade"] = (
        unit_dma["dma_valor"] / unit_dma["dma_dias"].replace(0, float("nan"))
    ).fillna(0.0)
    unit_dma = unit_dma[["unidade", "dma_unidade"]]

    # Faturamento por unidade — atribuído pela loja do CONTRATO (coral_por_loja_df),
    # não pela loja "de casa" do login.
    unit_fat = coral_por_loja_df.rename(columns={"fat_realizado_loja": "fat_realizado_unidade"})

    unit_meta = meta_equipe.groupby("unidade", as_index=False).agg(
        fat_meta_unidade=("meta_faturamento", "sum"),
    )
    unit = (
        unit_dma.merge(unit_fat, on="unidade", how="outer")
                .merge(unit_meta, on="unidade", how="outer")
                .fillna(0.0)
    )

    colab = colab.merge(unit, on="unidade", how="left")
    colab[["dma_unidade", "fat_realizado_unidade", "fat_meta_unidade"]] = colab[[
        "dma_unidade", "fat_realizado_unidade", "fat_meta_unidade"
    ]].fillna(0.0)

    # agrega por regional para Regionais
    colab_regs = colab[["unidade", "regional"]].drop_duplicates()

    reg_coral = coral.copy()
    reg_coral["unidade"] = reg_coral["unidade"].str.strip().str.upper()
    reg_coral = reg_coral.merge(colab_regs, on="unidade", how="left")
    reg_dma = reg_coral.groupby("regional", as_index=False).agg(
        dma_valor=("dma_valor", "sum"),
        dma_dias=("dma_dias", "sum"),
    )
    reg_dma["dma_regional"] = (
        reg_dma["dma_valor"] / reg_dma["dma_dias"].replace(0, float("nan"))
    ).fillna(0.0)
    reg_dma = reg_dma[["regional", "dma_regional"]]

    # Faturamento regional — soma do faturamento por loja do contrato
    # (coral_por_loja_df) das lojas daquela regional.
    loja_reg = coral_por_loja_df.merge(colab_regs, on="unidade", how="left")
    reg_fat = loja_reg.groupby("regional", as_index=False).agg(
        fat_realizado_regional=("fat_realizado_loja", "sum"),
    )

    reg_meta = meta_equipe.copy()
    reg_meta["unidade"] = reg_meta["unidade"].str.strip().str.upper() if "unidade" in reg_meta.columns else ""
    reg_meta = reg_meta.merge(colab_regs, on="unidade", how="left") if "unidade" in reg_meta.columns else pd.DataFrame()

    if not reg_meta.empty and "regional" in reg_meta.columns:
        reg_meta_agg = reg_meta.groupby("regional", as_index=False).agg(
            fat_meta_regional=("meta_faturamento", "sum"),
        )
    else:
        reg_meta_agg = pd.DataFrame(columns=["regional", "fat_meta_regional"])

    reg_agg = (
        reg_dma.merge(reg_fat, on="regional", how="outer")
               .merge(reg_meta_agg, on="regional", how="outer")
               .fillna(0.0)
    )

    colab = colab.merge(reg_agg, on="regional", how="left")
    colab[["dma_regional", "fat_realizado_regional", "fat_meta_regional"]] = colab[[
        "dma_regional", "fat_realizado_regional", "fat_meta_regional"
    ]].fillna(0.0)

    return colab


def _merge_frota(
    colab: pd.DataFrame,
    nonrev_df: pd.DataFrame,
    preventiva_df: pd.DataFrame,
    bate_patio_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Todos os DataFrames já vêm do loader com valores numéricos, unidade em
    maiúsculas e o código de loja já normalizado para o padrão TOTVS (CC).
    NONREV e Preventiva: não faz fillna — loja sem correspondência fica com
    NaN, e _validar_indicadores_por_loja() cancela o cálculo se isso acontecer.
    Bate Pátio: por decisão do usuário, loja sem correspondência vira 0.0 em
    vez de cancelar o cálculo.
    """
    colab = colab.merge(nonrev_df[["unidade", "nonrev_pct"]],       on="unidade", how="left")
    colab = colab.merge(preventiva_df[["unidade", "preventiva_pct"]], on="unidade", how="left")
    colab = colab.merge(bate_patio_df[["unidade", "bate_patio_pct"]], on="unidade", how="left")
    colab["bate_patio_pct"] = colab["bate_patio_pct"].fillna(0.0)
    return colab


# ---------------------------------------------------------------------------
# Cálculo por linha
# ---------------------------------------------------------------------------

def _calcular_linha(row: pd.Series, grupo: str, competencia: str) -> dict:
    elegivel, motivo = is_elegivel(row)
    resultado = {
        "matricula": row["matricula"],
        "nome":      row["nome"],
        "cargo":     row["cargo"],
        "grupo":     grupo,
        "unidade":   row["unidade"],
        "regional":  row["regional"],
        "salario_base":      row["salario_base"],
        "dias_trabalhados":  row["dias_trabalhados"],
        "elegivel":          elegivel,
        "motivo_inelegivel": motivo,
        "rv_base":           0.0,
        "rv_final":          0.0,
    }

    if not elegivel:
        return resultado

    # Base monetária sobre a qual os % são aplicados
    if grupo in GRUPOS_MODELO_PERCENTUAL:
        base_valor = row["salario_base"]
    else:
        base_valor = TETOS.get(row["cargo"], 200.0)

    # Indicadores já no escopo correto para cada grupo
    if grupo == "atendente":
        fat_real = row.get("faturamento_realizado", 0.0)
        fat_meta = row.get("meta_faturamento", 0.0)
        indicadores = {
            "dma":         row.get("dma", 0.0),
            "nps":         row.get("nps", 0.0),
            "faturamento": (fat_real / fat_meta * 100) if fat_meta > 0 else 0.0,
        }
    elif grupo in ("atendente_lider", "gestor"):
        fat_real = row.get("fat_realizado_unidade", 0.0)
        fat_meta = row.get("fat_meta_unidade", 0.0)
        indicadores = {
            "dma":         row.get("dma_unidade", 0.0),
            "nps":         row.get("nps", 0.0),
            "faturamento": (fat_real / fat_meta * 100) if fat_meta > 0 else 0.0,
        }
    elif grupo == "regional":
        fat_real = row.get("fat_realizado_regional", 0.0)
        fat_meta = row.get("fat_meta_regional", 0.0)
        indicadores = {
            "dma":         row.get("dma_regional", 0.0),
            "nps":         row.get("nps", 0.0),
            "faturamento": (fat_real / fat_meta * 100) if fat_meta > 0 else 0.0,
        }
    else:  # modelo teto fixo
        indicadores = {
            "nps":        row.get("nps", 0.0),
            "nonrev":     row.get("nonrev_pct", 0.0),
            "preventiva": row.get("preventiva_pct", 0.0),
            "bate_patio": row.get("bate_patio_pct", 0.0),
        }

    res = calculadora.calcular(grupo, base_valor, indicadores, competencia)
    resultado["rv_base"] = res["rv_base"]
    for ind, det in res["detalhes"].items():
        resultado[f"valor_{ind}"] = det["valor"]
        resultado[f"pct_{ind}"]   = det["pct"]

    resultado["rv_final"] = aplicar_proporcionalidade(res["rv_base"], row["dias_trabalhados"])
    return resultado


# ---------------------------------------------------------------------------
# Ponto de entrada do engine
# ---------------------------------------------------------------------------

def processar(data: dict, competencia: str) -> pd.DataFrame:
    """
    Recebe o dict de DataFrames retornado por loader.carregar_tudo()
    e a competência no formato "AAAA-MM".
    Retorna DataFrame com uma linha por colaborador e colunas de resultado.
    """
    colab = normalizar_colaboradores(data["colaboradores"])

    # Grupo vem direto da coluna grupo_calculo do TOTVS RM
    colab["grupo"] = colab["grupo_calculo"]
    sem_grupo = colab[colab["grupo"].isna() | (colab["grupo"] == "")]
    if not sem_grupo.empty:
        mats = sem_grupo["matricula"].unique().tolist()
        print(f"[AVISO] Colaboradores sem grupo_calculo preenchido (serão ignorados): {mats}")
    colab = colab[colab["grupo"].notna() & (colab["grupo"] != "")].copy()

    # Enriquece com indicadores
    colab = _merge_nps(colab, data["nps"])
    colab = _merge_coral(colab, data["coral"], data["coral_por_loja"], data["meta_faturamento"], data["mapeamento"])
    colab = _merge_frota(colab, data["nonrev"], data["preventiva"], data["bate_patio"])

    _validar_indicadores_por_loja(colab)

    # NPS regional: média das unidades na regional
    nps_reg = colab[["unidade", "regional", "nps"]].drop_duplicates("unidade")
    nps_reg = nps_reg.groupby("regional", as_index=False)["nps"].mean().rename(columns={"nps": "nps_regional"})
    colab = colab.merge(nps_reg, on="regional", how="left")
    colab.loc[colab["grupo"] == "regional", "nps"] = colab.loc[colab["grupo"] == "regional", "nps_regional"]
    colab["nps"] = colab["nps"].fillna(0.0)

    # Calcula RV linha a linha
    resultados = [_calcular_linha(row, row["grupo"], competencia) for _, row in colab.iterrows()]
    return pd.DataFrame(resultados)

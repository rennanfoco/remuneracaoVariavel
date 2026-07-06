"""
Carrega os parâmetros de RV a partir do arquivo referencias.xlsx.
Não edite os valores aqui — edite diretamente o referencias.xlsx.

Se o arquivo não existir, execute: python criar_referencias.py
"""

from pathlib import Path
import pandas as pd

_REF = Path(__file__).parent / "referencias.xlsx"


# ---------------------------------------------------------------------------
# Carregamento do referencias.xlsx
# ---------------------------------------------------------------------------

def _exigir_ref():
    if not _REF.exists():
        raise FileNotFoundError(
            f"\nArquivo de referencias nao encontrado: {_REF}\n"
            f"Execute primeiro:  python criar_referencias.py\n"
        )


def _to_float(val) -> float | None:
    """Converte para float; retorna None se vazio ou não numérico (ignora linhas de descrição)."""
    try:
        return float(val) if pd.notna(val) else None
    except (ValueError, TypeError):
        return None


def _parse_regras(xls: pd.ExcelFile) -> dict:
    """
    Lê a aba Regras_Calculo e retorna:
      REGRAS[grupo][indicador] = {
          faixa1_min, faixa1_max, faixa2_min, faixa2_max,  # None quando não aplicável
          faixa1_pct, faixa2_pct,                           # decimal (0.15 = 15%)
          direcao,                                           # "maior" | "menor"
          chave_meta,                                        # str | None
      }
    Linhas com valores não numéricos nos campos de faixa são ignoradas (ex: linhas de
    instrução do template).
    """
    df = xls.parse("Regras_Calculo")
    result: dict = {}
    for _, row in df.iterrows():
        # minúsculo para casar com grupo_calculo (Cargos) e GRUPOS_MODELO_*,
        # que também são sempre minúsculos — evita bug de "Mecanico" x "mecanico".
        grupo     = str(row["grupo"]).strip().lower()
        indicador = str(row["indicador"]).strip().lower()
        entry: dict = {}
        for col in ("faixa1_min", "faixa1_max", "faixa2_min", "faixa2_max"):
            entry[col] = _to_float(row[col]) if col in row.index else None
        pct1 = _to_float(row.get("faixa1_pct"))
        pct2 = _to_float(row.get("faixa2_pct"))
        if pct1 is None and pct2 is None:
            continue  # linha de instrução — ignora
        entry["faixa1_pct"] = pct1 if pct1 is not None else 0.0
        entry["faixa2_pct"] = pct2 if pct2 is not None else 0.0
        entry["direcao"]    = str(row["direcao"]).strip() if "direcao" in row.index and pd.notna(row["direcao"]) else "maior"
        chave = row.get("chave_meta")
        entry["chave_meta"] = str(chave).strip() if chave is not None and pd.notna(chave) else None
        result.setdefault(grupo, {})[indicador] = entry
    return result


def _parse_cargos(xls: pd.ExcelFile) -> dict:
    """
    Lê a aba Cargos e retorna dict cargo (maiúsculo) → grupo_calculo.
    Usado pelo totvs_client para mapear o campo NOME1 da API.
    """
    df = xls.parse("Cargos")
    return {
        str(row["cargo"]).strip().upper(): str(row["grupo_calculo"]).strip().lower()
        for _, row in df.iterrows()
    }


def _parse_tetos(xls: pd.ExcelFile) -> dict:
    df = xls.parse("Tetos")
    # aceita tanto "teto" (gerado por criar_referencias.py) quanto "teto (R$)" (template)
    teto_col = next((c for c in df.columns if str(c).strip().lower().startswith("teto")), df.columns[1])
    result = {}
    for _, row in df.iterrows():
        v = _to_float(row[teto_col])
        if v is not None:
            result[str(row["cargo"]).strip().upper()] = v
    return result


def _parse_metas(xls: pd.ExcelFile) -> dict:
    df = xls.parse("Metas_Mensais")
    df["mes"] = df["mes"].astype(str).str.strip()
    result = {}
    for _, row in df.iterrows():
        mes   = str(row["mes"]).strip()
        chave = str(row["chave"]).strip()
        entry = {}
        for col in ("faixa1_min", "faixa1_max", "faixa2_min", "faixa2_max"):
            v = _to_float(row[col]) if col in row.index else None
            if v is not None:
                entry[col] = v
        if entry:  # ignora linhas sem nenhum valor numérico (instrução ou vazia)
            result.setdefault(mes, {})[chave] = entry
    return result


def _parse_totvs(xls: pd.ExcelFile) -> dict:
    df = xls.parse("TOTVS")
    return dict(zip(
        df["parametro"].astype(str).str.strip(),
        df["valor"].astype(str).str.strip(),
    ))


def _parse_grupos_modelo(xls: pd.ExcelFile) -> dict:
    """
    Lê a aba Grupos e retorna dict grupo (minúsculo) -> modelo
    ("percentual" | "teto_fixo"). Define se a base do prêmio daquele grupo é
    o salário do colaborador (percentual) ou um teto fixo em R$ (teto_fixo,
    ver aba Tetos). Linhas com modelo vazio/inválido são ignoradas (instrução).
    """
    df = xls.parse("Grupos")
    result: dict = {}
    for _, row in df.iterrows():
        grupo  = str(row["grupo"]).strip().lower()
        modelo = str(row.get("modelo")).strip().lower() if pd.notna(row.get("modelo")) else ""
        if modelo not in ("percentual", "teto_fixo"):
            continue  # linha de instrução ou modelo não reconhecido — ignora
        result[grupo] = modelo
    return result


def _carregar():
    _exigir_ref()
    xls           = pd.ExcelFile(_REF)
    regras        = _parse_regras(xls)
    cargos        = _parse_cargos(xls)
    tetos         = _parse_tetos(xls)
    metas         = _parse_metas(xls)
    totvs         = _parse_totvs(xls)
    grupos_modelo = _parse_grupos_modelo(xls)
    return regras, cargos, tetos, metas, totvs, grupos_modelo


# ---------------------------------------------------------------------------
# Variáveis exportadas — usadas pelo restante do código
# ---------------------------------------------------------------------------
REGRAS, CARGOS_GRUPO, TETOS, METAS_MENSAIS, _TOTVS, _GRUPOS_MODELO = _carregar()

TOTVS_COD_EVENTO_RV = _TOTVS.get("cod_evento_rv", "9050")
TOTVS_COD_COLIGADA  = _TOTVS.get("cod_coligada",  "1")
TOTVS_SEPARADOR     = _TOTVS.get("separador",     ";")

# Grupos por modelo de cálculo — vem da aba Grupos do referencias.xlsx.
# Define se a base monetária do prêmio é o salário (%) ou um teto fixo (R$).
GRUPOS_MODELO_PERCENTUAL = {g for g, m in _GRUPOS_MODELO.items() if m == "percentual"}
GRUPOS_MODELO_TETO       = {g for g, m in _GRUPOS_MODELO.items() if m == "teto_fixo"}

_grupos_sem_modelo = set(REGRAS) - GRUPOS_MODELO_PERCENTUAL - GRUPOS_MODELO_TETO
if _grupos_sem_modelo:
    raise ValueError(
        f"Grupo(s) com regras em Regras_Calculo mas sem modelo definido na aba "
        f"'Grupos': {sorted(_grupos_sem_modelo)}. Adicione uma linha para cada um "
        f"(modelo = 'percentual' ou 'teto_fixo') antes de rodar o cálculo."
    )

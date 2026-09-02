"""
Carrega os parâmetros de RV a partir do arquivo referencias.xlsx.
Não edite os valores aqui — edite diretamente o referencias.xlsx.

Se o arquivo não existir, execute: python criar_referencias.py

O caminho pode ser sobrescrito pela variável de ambiente REFERENCIAS_XLSX_PATH
(usado pelo portal web V2, que exporta as regras do banco para um arquivo
temporário por execução em vez de compartilhar o referencias.xlsx do projeto
entre execuções concorrentes). Sem essa variável, comportamento idêntico ao
de sempre — usa o referencias.xlsx na raiz do projeto.
"""

import os
from pathlib import Path
import pandas as pd

_REF = Path(os.environ.get("REFERENCIAS_XLSX_PATH") or (Path(__file__).parent / "referencias.xlsx"))


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
    Lê a aba Regras_Calculo em formato LONGO — uma linha por faixa, não uma
    coluna por faixa — o que permite qualquer quantidade de faixas por
    indicador (só adicionar mais linhas, sem alterar código).

    Retorna:
      REGRAS[grupo][indicador][unidade] = {
          "direcao":    "maior" | "menor",
          "chave_meta": str | None,   # se definido, min/max vêm de METAS_MENSAIS
          "depende_indicador": str | None,  # nome de outro indicador do mesmo
                                             # grupo — se definido, este indicador
                                             # só conta (pct > 0) quando o valor
                                             # REAL do indicador referenciado for
                                             # >= depende_valor_min
          "depende_valor_min": float | None,
          "faixas": [
              {"faixa": int, "min": float|None, "max": float|None, "pct": float},
              ...  # uma entrada por faixa, em qualquer ordem
          ],
      }
    `unidade` é None para a regra padrão (nacional) — a mesma coisa de
    sempre — ou o código de uma loja específica, quando essa loja tem uma
    regra própria que sobrescreve a padrão só pra quem trabalha lá (ver
    coluna opcional `unidade` da planilha; rv/calculators/calculadora.py
    usa a regra da loja do colaborador se existir, senão cai na padrão).

    Linhas sem grupo/indicador/faixa/pct válidos são ignoradas (instrução do template).
    """
    df = xls.parse("Regras_Calculo")
    result: dict = {}
    for _, row in df.iterrows():
        # minúsculo para casar com grupo_calculo (Cargos) e GRUPOS_MODELO_*,
        # que também são sempre minúsculos — evita bug de "Mecanico" x "mecanico".
        grupo     = str(row.get("grupo", "")).strip().lower()
        indicador = str(row.get("indicador", "")).strip().lower()
        faixa_num = _to_float(row.get("faixa"))
        pct       = _to_float(row.get("pct"))
        if not grupo or grupo == "nan" or not indicador or indicador == "nan" or faixa_num is None or pct is None:
            continue  # linha de instrução ou incompleta — ignora
        faixa_num = int(faixa_num)

        chave_bruta = row.get("chave_meta")
        depende_bruto = row.get("depende_indicador")
        unidade_bruta = row.get("unidade")
        unidade = str(unidade_bruta).strip().upper() if pd.notna(unidade_bruta) and str(unidade_bruta).strip() else None

        variantes = result.setdefault(grupo, {}).setdefault(indicador, {})
        indicador_entry = variantes.setdefault(unidade, {
            "direcao":    str(row.get("direcao")).strip().lower() if pd.notna(row.get("direcao")) else "maior",
            "chave_meta": str(chave_bruta).strip() if pd.notna(chave_bruta) else None,
            "depende_indicador": str(depende_bruto).strip().lower() if pd.notna(depende_bruto) else None,
            "depende_valor_min": _to_float(row.get("depende_valor_min")),
            "faixas":     [],
        })
        indicador_entry["faixas"].append({
            "faixa": faixa_num,
            "min":   _to_float(row.get("valor_min")),
            "max":   _to_float(row.get("valor_max")),
            "pct":   pct,
        })
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
    """
    Lê a aba Metas_Mensais em formato LONGO — uma linha por faixa —, mesma
    lógica de Regras_Calculo. Usada para indicadores cujo limite varia por mês
    (ex: NPS, NONREV) via chave_meta.

    Retorna:
      METAS_MENSAIS[mes][chave] = [
          {"faixa": int, "min": float|None, "max": float|None}, ...
      ]
    """
    df = xls.parse("Metas_Mensais")
    result = {}
    for _, row in df.iterrows():
        mes       = str(row.get("mes", "")).strip()
        chave     = str(row.get("chave", "")).strip()
        faixa_num = _to_float(row.get("faixa"))
        if not mes or mes == "nan" or not chave or chave == "nan" or faixa_num is None:
            continue  # linha de instrução, vazia ou incompleta — ignora
        result.setdefault(mes, {}).setdefault(chave, []).append({
            "faixa": int(faixa_num),
            "min":   _to_float(row.get("valor_min")),
            "max":   _to_float(row.get("valor_max")),
        })
    return result


def _parse_metas_faturamento_regional(xls: pd.ExcelFile) -> dict:
    """
    Lê a aba Metas_Faturamento_Regional (mes, regional, meta) — a meta de
    faturamento de cada Regional em R$, digitada direto na planilha, em vez
    de somada a partir das metas individuais dos atendentes das lojas.

    Tolerante à ausência da aba (retorna {}) para não quebrar um
    referencias.xlsx antigo, de antes dessa aba existir — a falta de uma
    meta específica só é um erro na hora de calcular aquela regional/mês
    (ver rv/engine.py), não no import deste módulo.

    Retorna:
      METAS_FATURAMENTO_REGIONAL[mes][regional] = valor (float)
    """
    if "Metas_Faturamento_Regional" not in xls.sheet_names:
        return {}
    df = xls.parse("Metas_Faturamento_Regional")
    result: dict = {}
    for _, row in df.iterrows():
        mes      = str(row.get("mes", "")).strip()
        regional = str(row.get("regional", "")).strip().upper()
        meta     = _to_float(row.get("meta"))
        if not mes or mes == "nan" or not regional or regional == "NAN" or meta is None:
            continue  # linha de instrução, vazia ou incompleta — ignora
        result.setdefault(mes, {})[regional] = meta
    return result


def _parse_lojas(xls: pd.ExcelFile) -> dict:
    """
    Lê a aba Lojas (unidade, regional) — cadastro explícito de qual regional
    cada loja pertence, independente de quem está na folha do mês.

    Sem essa aba, o sistema só sabia a regional de uma loja através de um
    colaborador lotado nela — uma loja sem NINGUÉM na folha (ex: reforma,
    troca de gestão) desaparecia dos totais da regional sem aviso, exigindo
    cadastrar uma pessoa fictícia só pra loja "existir" no cálculo. Ver
    rv/engine.py::_merge_coral.

    Tolerante à ausência da aba (retorna {}) para não quebrar um
    referencias.xlsx antigo — nesse caso o sistema cai de volta no
    comportamento anterior (mapeamento só via colaboradores da folha).

    Retorna:
      LOJA_REGIONAL[unidade] = regional
    """
    if "Lojas" not in xls.sheet_names:
        return {}
    df = xls.parse("Lojas")
    result: dict = {}
    for _, row in df.iterrows():
        unidade  = str(row.get("unidade", "")).strip().upper()
        regional = str(row.get("regional", "")).strip().upper()
        if not unidade or unidade == "NAN" or not regional or regional == "NAN":
            continue  # linha de instrução, vazia ou incompleta — ignora
        result[unidade] = regional
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
    xls              = pd.ExcelFile(_REF)
    regras           = _parse_regras(xls)
    cargos           = _parse_cargos(xls)
    tetos            = _parse_tetos(xls)
    metas            = _parse_metas(xls)
    metas_fat_reg    = _parse_metas_faturamento_regional(xls)
    lojas            = _parse_lojas(xls)
    totvs            = _parse_totvs(xls)
    grupos_modelo    = _parse_grupos_modelo(xls)
    return regras, cargos, tetos, metas, metas_fat_reg, lojas, totvs, grupos_modelo


# ---------------------------------------------------------------------------
# Variáveis exportadas — usadas pelo restante do código
# ---------------------------------------------------------------------------
(
    REGRAS, CARGOS_GRUPO, TETOS, METAS_MENSAIS, METAS_FATURAMENTO_REGIONAL,
    LOJA_REGIONAL, _TOTVS, _GRUPOS_MODELO,
) = _carregar()

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

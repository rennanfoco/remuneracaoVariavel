"""
Calculadora genérica de RV, guiada pelos dados de REGRAS (referencias.xlsx > Regras_Calculo).

Para cada grupo, o Excel define quais indicadores contam, os limites de faixa e os
percentuais aplicados sobre a base (salário ou teto).  Adicionar ou remover um indicador
de um cargo exige apenas uma linha na planilha — sem alterar código.

Faturamento é recebido já como % de atingimento (ex: 103.5 significa 103,5% da meta).
"""

from config import REGRAS, METAS_MENSAIS


def _avaliar_faixa(valor: float, regra: dict, competencia: str) -> str:
    """
    Retorna "faixa2" | "faixa1" | "zero" para o valor dado.

    Para métricas com chave_meta, os limites vêm de METAS_MENSAIS[competencia][chave].
    Para métricas fixas, os limites estão diretamente em `regra`.
    A avaliação de faixa2 tem prioridade sobre faixa1.
    """
    chave = regra.get("chave_meta")
    if chave:
        metas_mes = METAS_MENSAIS.get(competencia, {})
        t = metas_mes.get(chave)
        if t is None:
            raise KeyError(
                f"Meta '{chave}' nao encontrada para competencia '{competencia}'. "
                f"Adicione o bloco correspondente em Metas_Mensais no referencias.xlsx."
            )
    else:
        t = regra

    direcao = regra.get("direcao", "maior")

    if direcao == "menor":
        # NONREV: quanto menor, melhor
        f2_max = t.get("faixa2_max")
        f1_min = t.get("faixa1_min")
        f1_max = t.get("faixa1_max")
        if f2_max is not None and valor <= f2_max:
            return "faixa2"
        if f1_min is not None and f1_max is not None and f1_min <= valor <= f1_max:
            return "faixa1"
    else:
        # Padrão: quanto maior, melhor
        f2_min = t.get("faixa2_min")
        f1_min = t.get("faixa1_min")
        f1_max = t.get("faixa1_max")
        if f2_min is not None and valor >= f2_min:
            return "faixa2"
        if f1_min is not None and f1_max is not None and f1_min <= valor < f1_max:
            return "faixa1"

    return "zero"


def calcular(grupo: str, base: float, indicadores: dict, competencia: str) -> dict:
    """
    Calcula o RV para um colaborador.

    Parâmetros:
      grupo       — grupo do cargo (ex: "atendente", "lider_frota")
      base        — salário base (modelo %) ou teto em R$ (modelo fixo)
      indicadores — dict com os valores realizados dos indicadores do grupo;
                    "faturamento" deve vir como % de atingimento (ex: 103.5)
      competencia — "AAAA-MM"

    Retorna:
      {
        "rv_base": float,
        "detalhes": {
          indicador: {"faixa": "faixa1"|"faixa2"|"zero", "pct": float, "valor": float}
        }
      }
    """
    regras_grupo = REGRAS.get(grupo, {})
    rv_base = 0.0
    detalhes: dict = {}

    for indicador, regra in regras_grupo.items():
        valor = float(indicadores.get(indicador, 0.0))
        faixa = _avaliar_faixa(valor, regra, competencia)
        pct   = regra.get(f"faixa{faixa[-1]}_pct", 0.0) if faixa != "zero" else 0.0
        rv_base += base * pct
        detalhes[indicador] = {"faixa": faixa, "pct": pct, "valor": valor}

    return {"rv_base": round(rv_base, 2), "detalhes": detalhes}

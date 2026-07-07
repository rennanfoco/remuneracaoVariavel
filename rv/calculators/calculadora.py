"""
Calculadora genérica de RV, guiada pelos dados de REGRAS (referencias.xlsx > Regras_Calculo).

Para cada grupo, o Excel define quais indicadores contam, os limites de cada faixa e os
percentuais aplicados sobre a base (salário ou teto). Adicionar ou remover um indicador,
ou uma FAIXA (ex: faixa3), exige apenas uma linha na planilha — sem alterar código.

Faturamento é recebido já como % de atingimento (ex: 103.5 significa 103,5% da meta).
"""

from config import REGRAS, METAS_MENSAIS


def _avaliar_faixa(valor: float, regra: dict, competencia: str) -> tuple[int, float]:
    """
    Retorna (numero_da_faixa, pct) para o valor dado. Se nenhuma faixa for
    atingida, retorna (0, 0.0).

    Suporta qualquer quantidade de faixas: avalia da maior para a menor
    (faixa mais alta = melhor resultado) e retorna a primeira que bater.

    Para métricas com chave_meta, os limites (min/max) vêm de
    METAS_MENSAIS[competencia][chave] — o pct de cada faixa continua vindo de
    Regras_Calculo (o mês só afeta os limites, não os percentuais).
    """
    direcao = regra.get("direcao", "maior")
    faixas  = regra["faixas"]
    chave   = regra.get("chave_meta")

    if chave:
        metas_mes = METAS_MENSAIS.get(competencia, {})
        limites_mes = metas_mes.get(chave)
        if limites_mes is None:
            raise KeyError(
                f"Meta '{chave}' nao encontrada para competencia '{competencia}'. "
                f"Adicione o bloco correspondente em Metas_Mensais no referencias.xlsx."
            )
        limites_por_faixa = {l["faixa"]: l for l in limites_mes}
    else:
        limites_por_faixa = None

    for f in sorted(faixas, key=lambda x: x["faixa"], reverse=True):
        if limites_por_faixa is not None:
            limite = limites_por_faixa.get(f["faixa"])
            if limite is None:
                continue  # mês não define limite para essa faixa específica
            f_min, f_max = limite["min"], limite["max"]
        else:
            f_min, f_max = f["min"], f["max"]

        if direcao == "menor":
            # quanto menor o valor, melhor (ex: NONREV)
            if f_max is not None and valor <= f_max and (f_min is None or valor >= f_min):
                return f["faixa"], f["pct"]
        else:
            # quanto maior o valor, melhor (padrão)
            if f_min is not None and valor >= f_min and (f_max is None or valor < f_max):
                return f["faixa"], f["pct"]

    return 0, 0.0


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
          indicador: {"faixa": int, "pct": float, "valor": float}  # faixa=0 quando nao atingiu nenhuma
        }
      }
    """
    regras_grupo = REGRAS.get(grupo, {})
    rv_base = 0.0
    detalhes: dict = {}

    for indicador, regra in regras_grupo.items():
        valor = float(indicadores.get(indicador, 0.0))
        faixa_num, pct = _avaliar_faixa(valor, regra, competencia)
        rv_base += base * pct
        detalhes[indicador] = {"faixa": faixa_num, "pct": pct, "valor": valor}

    return {"rv_base": round(rv_base, 2), "detalhes": detalhes}

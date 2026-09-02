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
            # quanto maior o valor, melhor (padrão) — limites min e max são
            # ambos INCLUSIVOS (intervalo fechado [min, max]), igual à direção
            # "menor". Não há risco de sobreposição indevida entre faixas
            # adjacentes: a faixa mais alta é sempre avaliada primeiro e vence
            # em caso de empate exato na fronteira (ex: faixa1_max == faixa2_min).
            if f_min is not None and valor >= f_min and (f_max is None or valor <= f_max):
                return f["faixa"], f["pct"]

    return 0, 0.0


def _regra_da_loja(variantes: dict, unidade: str | None) -> dict | None:
    """
    `variantes` é REGRAS[grupo][indicador] — um dict {unidade: regra}, com a
    entrada None sendo a regra padrão (nacional). Usa a regra específica da
    loja do colaborador se existir; senão cai na padrão. Retorna None só se
    nem a loja nem o padrão tiverem regra (indicador não configurado pra
    esse grupo).
    """
    return variantes.get(unidade) or variantes.get(None)


def calcular(grupo: str, base: float, indicadores: dict, competencia: str, unidade: str | None = None) -> dict:
    """
    Calcula o RV para um colaborador.

    Parâmetros:
      grupo       — grupo do cargo (ex: "atendente", "lider_frota")
      base        — salário base (modelo %) ou teto em R$ (modelo fixo)
      indicadores — dict com os valores realizados dos indicadores do grupo;
                    "faturamento" deve vir como % de atingimento (ex: 103.5)
      competencia — "AAAA-MM"
      unidade     — código da loja do colaborador; usada só pra escolher entre
                    a regra padrão (nacional) e uma regra específica daquela
                    loja, quando existir (ver Regras_Calculo > coluna unidade)

    Retorna:
      {
        "rv_base": float,
        "detalhes": {
          indicador: {
            "faixa": int, "pct": float, "valor": float,  # faixa=0 quando nao atingiu nenhuma
            "bloqueado": bool,       # True se zerado por dependência não satisfeita
            "motivo_bloqueio": str,  # só quando bloqueado=True
          }
        }
      }

    Dependência entre indicadores (Regras_Calculo > depende_indicador /
    depende_valor_min): calculado em 2 passadas — primeiro avalia a faixa de
    TODOS os indicadores normalmente (idêntico a antes), depois zera o pct de
    quem declarou depender de outro indicador que não atingiu o valor mínimo
    exigido. A checagem usa o valor REAL do indicador referenciado (não a
    faixa dele), então funciona tanto pra um valor solto (ex: DMA >= 40)
    quanto pra um indicador já expresso em % (ex: faturamento >= 100).
    """
    regras_grupo = REGRAS.get(grupo, {})
    detalhes: dict = {}

    # 1ª passada: avalia cada indicador isoladamente, como sempre foi — só
    # que a regra usada é a da loja do colaborador, se existir, senão a padrão.
    regras_usadas: dict = {}
    for indicador, variantes in regras_grupo.items():
        regra = _regra_da_loja(variantes, unidade)
        if regra is None:
            continue
        regras_usadas[indicador] = regra
        valor = float(indicadores.get(indicador, 0.0))
        faixa_num, pct = _avaliar_faixa(valor, regra, competencia)
        detalhes[indicador] = {"faixa": faixa_num, "pct": pct, "valor": valor, "bloqueado": False}

    # 2ª passada: zera quem depende de outro indicador que não bateu o mínimo.
    for indicador, regra in regras_usadas.items():
        dep_indicador = regra.get("depende_indicador")
        dep_valor_min = regra.get("depende_valor_min")
        if not dep_indicador or dep_valor_min is None:
            continue
        valor_dependencia = float(indicadores.get(dep_indicador, 0.0))
        if valor_dependencia < dep_valor_min:
            det = detalhes[indicador]
            det["pct"] = 0.0
            det["bloqueado"] = True
            det["motivo_bloqueio"] = (
                f"{indicador} bloqueado: requer {dep_indicador} >= {dep_valor_min} "
                f"(atual: {valor_dependencia})"
            )

    rv_base = sum(base * det["pct"] for det in detalhes.values())
    return {"rv_base": round(rv_base, 2), "detalhes": detalhes}

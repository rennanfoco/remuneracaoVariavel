"""
Regras de elegibilidade e proporcionalidade da RV.

Regras conforme documentação:
- A API do TOTVS RM já filtra apenas colaboradores ativos — não há desligados.
- Dias trabalhados < 30 → RV proporcional (admissão no mês, afastamento > 15 dias).
- Afastamentos <= 15 dias não impactam (dias_trabalhados = 30 nesses casos).
"""


def is_elegivel(row: dict) -> tuple[bool, str]:
    """
    Retorna (elegivel, motivo).
    'dias_trabalhados' deve ser int [0..30].
    """
    if row.get("dias_trabalhados", 30) == 0:
        return False, "Zero dias trabalhados"
    return True, ""


def aplicar_proporcionalidade(rv_base: float, dias_trabalhados: int) -> float:
    """
    RV proporcional = (RV calculada / 30) × dias trabalhados.
    Se dias_trabalhados == 30, retorna rv_base sem alteração.
    """
    if dias_trabalhados >= 30:
        return round(rv_base, 2)
    return round((rv_base / 30) * dias_trabalhados, 2)

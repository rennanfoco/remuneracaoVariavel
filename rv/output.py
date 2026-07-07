"""
Geração dos arquivos de saída:
  1. TXT no layout de importação do TOTVS RM (folha de pagamento)
  2. Excel detalhado para validação pelo gestor

⚠️  ATENÇÃO — Layout do TXT:
    O formato abaixo é uma proposta baseada no padrão comum de importação do TOTVS RM.
    Confirme o layout exato com o administrador do TOTVS antes de usar em produção.

Formato atual (uma linha por colaborador com RV > 0, sem header, separador ';'):
    Chapa;ddmmaaaa;Evento;;0,00;Valor;Valor;S;;
    Ex: 000200;31012025;1010;;0,00;1000,00;1000,00;S;;
"""

import calendar
from pathlib import Path
import pandas as pd

from config import TOTVS_COD_EVENTO_RV


def _ultimo_dia_mes(competencia: str) -> str:
    """Retorna o último dia do mês no formato ddmmaaaa. Ex: '2026-06' → '30062026'."""
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    ultimo = calendar.monthrange(ano, mes)[1]
    return f"{ultimo:02d}{mes:02d}{ano}"


def _fmt_valor(v: float) -> str:
    """Formata valor no padrão brasileiro: 1000.50 → '1000,50'."""
    return f"{v:.2f}".replace(".", ",")


def gerar_txt(df_resultados: pd.DataFrame, competencia: str, output_dir: Path) -> Path:
    """
    Gera o arquivo TXT de importação para o TOTVS RM.

    Formato (sem header, separador ';'):
      Chapa;ddmmaaaa;Evento;;0,00;Valor;Valor;S;;

    Exemplo:
      000200;31012025;1010;;0,00;1000,00;1000,00;S;;
    """
    data_totvs = _ultimo_dia_mes(competencia)
    evento     = TOTVS_COD_EVENTO_RV

    elegíveis = df_resultados[
        df_resultados["elegivel"] & (df_resultados["rv_final"] > 0)
    ].copy().sort_values("matricula")

    linhas = []
    for _, row in elegíveis.iterrows():
        valor = _fmt_valor(row["rv_final"])
        linhas.append(
            f"{row['matricula']};{data_totvs};{evento};;0,00;{valor};{valor};S;;"
        )

    caminho = output_dir / f"rv_{competencia}.txt"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


RENOMEAR_COLUNAS = {
    "matricula":          "Matrícula",
    "nome":               "Nome",
    "cargo":              "Cargo",
    "grupo":              "Grupo RV",
    "unidade":            "Unidade",
    "regional":           "Regional",
    "salario_base":       "Salário Base (R$)",
    "dias_trabalhados":   "Dias Trabalhados",
    "elegivel":           "Elegível",
    "premio_rv":          "Prêmio RV (R$)",
    "rv_base":            "RV Bruta (antes proporcional) (R$)",
    "salario_total":      "Salário Total (R$)",
    "valor_dma":          "DMA",
    "pct_dma":            "Multiplicador DMA",
    "valor_nps":          "NPS",
    "pct_nps":            "Multiplicador NPS",
    "valor_faturamento":  "Faturamento (% Atingimento)",
    "pct_faturamento":    "Multiplicador Faturamento",
    "valor_nonrev":       "NONREV (%)",
    "pct_nonrev":         "Multiplicador NONREV",
    "valor_preventiva":   "Preventiva (%)",
    "pct_preventiva":     "Multiplicador Preventiva",
    "valor_bate_patio":   "Bate Pátio (%)",
    "pct_bate_patio":     "Multiplicador Bate Pátio",
}

COLUNAS_ORDEM = [
    "matricula", "nome", "cargo", "grupo", "unidade", "regional",
    "salario_base", "dias_trabalhados", "elegivel",
    "premio_rv", "rv_base", "salario_total",
    "valor_dma", "pct_dma",
    "valor_nps", "pct_nps",
    "valor_faturamento", "pct_faturamento",
    "valor_nonrev", "pct_nonrev",
    "valor_preventiva", "pct_preventiva",
    "valor_bate_patio", "pct_bate_patio",
]


def gerar_relatorio(df_resultados: pd.DataFrame, competencia: str, output_dir: Path) -> Path:
    """
    Gera Excel detalhado para validação pelo gestor.
    Inclui todas as linhas com o valor de cada indicador e o multiplicador aplicado.
    """
    df = df_resultados.copy()

    # Colunas calculadas
    df["premio_rv"]    = df["rv_final"]
    df["salario_total"] = df["salario_base"] + df["premio_rv"]

    # Seleciona e ordena colunas existentes
    colunas = [c for c in COLUNAS_ORDEM if c in df.columns]
    df_out = df[colunas].rename(columns=RENOMEAR_COLUNAS)

    # Aba de resumo por grupo
    resumo = df.groupby("grupo").agg(
        Total=("matricula", "count"),
        Elegíveis=("elegivel", "sum"),
        Com_Prêmio=("premio_rv", lambda x: (x > 0).sum()),
        Valor_Total_RV=("premio_rv", "sum"),
        Prêmio_Médio=("premio_rv", "mean"),
        Salário_Total_Folha=("salario_total", "sum"),
    ).reset_index().rename(columns={"grupo": "Grupo RV"})

    nome_arquivo = f"rv_{competencia}_relatorio.xlsx"
    caminho = output_dir / nome_arquivo

    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        df_out.to_excel(writer, sheet_name="Detalhado", index=False)
        resumo.to_excel(writer, sheet_name="Resumo por Grupo", index=False)

    return caminho

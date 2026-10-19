"""
Busca os colaboradores do mês na API do TOTVS RM (consulta API.04) e grava num CSV no formato que o
motor lê (colaboradores_rm.csv). O portal usa isto no botão "Buscar no TOTVS" da aba Cálculo: o
resultado fica guardado como a base de colaboradores da competência — com os dias trabalhados DAQUELE
mês e a lista de ativos no momento da busca.

Uso:
  python exportar_colaboradores.py --competencia 2026-09 --saida colaboradores_rm.csv

Sai com código 1 e a mensagem no stderr se o TOTVS não responder ou recusar.
"""

import argparse
import sys

from rv.totvs_client import buscar_colaboradores, salvar_colaboradores_csv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competencia", required=True, help="AAAA-MM")
    parser.add_argument("--saida", required=True, help="Caminho do CSV a gerar")
    args = parser.parse_args()

    ano, mes = args.competencia.split("-")
    try:
        df = buscar_colaboradores(mes, ano)
    except Exception as e:
        print(f"[ERRO] {e}", file=sys.stderr)
        sys.exit(1)

    salvar_colaboradores_csv(df, args.saida)
    print(f"{len(df)} colaboradores gravados em {args.saida}")


if __name__ == "__main__":
    main()

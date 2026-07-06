"""
Ponto de entrada da automação de Remuneração Variável.

Uso:
  python main.py --competencia 2026-06
  python main.py --competencia 2026-06 --input data/input --output data/output
  python main.py --competencia 2026-06 --sample   (usa arquivos de exemplo em samples/)
"""

import argparse
import sys
from pathlib import Path

from rv.loader import carregar_tudo
from rv.engine import processar
from rv.output import gerar_txt, gerar_relatorio


def main():
    parser = argparse.ArgumentParser(
        description="Apuração de Remuneração Variável — geração do TXT TOTVS RM"
    )
    parser.add_argument(
        "--competencia", required=True,
        help="Competência no formato AAAA-MM  (ex: 2026-06)",
    )
    parser.add_argument(
        "--input", default="data/input",
        help="Diretório com os arquivos de entrada (padrão: data/input)",
    )
    parser.add_argument(
        "--output", default="data/output",
        help="Diretório para os arquivos gerados (padrão: data/output)",
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Usa os arquivos de exemplo da pasta samples/ (para testes)",
    )
    parser.add_argument(
        "--api", action="store_true",
        help="Busca colaboradores direto da API do TOTVS RM (requer .env configurado)",
    )
    args = parser.parse_args()

    input_dir  = Path("samples") if args.sample else Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Apuração RV — Competência: {args.competencia}")
    print(f"  Input : {input_dir.resolve()}")
    print(f"  Output: {output_dir.resolve()}")
    print(f"{'='*60}\n")

    # 1. Colaboradores: API ou arquivo
    colab_df = None
    usar_api = args.api or (
        not args.sample and not (input_dir / "colaboradores_rm.csv").exists()
    )

    if usar_api:
        from rv.totvs_client import buscar_colaboradores
        ano, mes = args.competencia.split("-")
        print("Buscando colaboradores na API do TOTVS RM...")
        try:
            colab_df = buscar_colaboradores(mes, ano)
            print(f"  OK — {len(colab_df)} colaboradores obtidos via API.\n")
        except Exception as e:
            print(f"\n[ERRO] Falha ao buscar colaboradores via API: {e}")
            sys.exit(1)

    print("Carregando arquivos de entrada...")
    try:
        data = carregar_tudo(input_dir, colaboradores_df=colab_df)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n[ERRO] {e}")
        sys.exit(1)
    n_arquivos = len([k for k in data if k != "coral_por_loja"])  # chave derivada, não é um arquivo próprio
    print(f"  OK — {n_arquivos} arquivos carregados.\n")

    # 2. Processa e calcula
    print("Calculando RV...")
    try:
        df = processar(data, args.competencia)
    except (KeyError, ValueError) as e:
        print(f"\n[ERRO] {e}")
        sys.exit(1)

    total          = len(df)
    elegiveis      = df["elegivel"].sum()
    com_premio     = (df["rv_final"] > 0).sum()
    sem_premio     = elegiveis - com_premio
    inelegiveis    = total - elegiveis
    valor_total    = df["rv_final"].sum()

    print(f"  Colaboradores processados : {total}")
    print(f"  Elegíveis                 : {elegiveis}")
    print(f"  Com prêmio                : {com_premio}")
    print(f"  Sem prêmio (não atingiu)  : {sem_premio}")
    print(f"  Inelegíveis               : {inelegiveis}")
    print(f"  Valor total RV            : R$ {valor_total:,.2f}\n")

    # 3. Gera outputs
    print("Gerando arquivos de saída...")
    txt_path      = gerar_txt(df, args.competencia, output_dir)
    relatorio_path = gerar_relatorio(df, args.competencia, output_dir)

    print(f"  TXT TOTVS : {txt_path}")
    print(f"  Relatório : {relatorio_path}")
    print(f"\n{'='*60}")
    print("  Processamento concluído com sucesso.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

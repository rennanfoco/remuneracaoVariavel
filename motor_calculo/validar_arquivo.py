"""
Valida um arquivo de entrada antes de o portal guardá-lo (aba Arquivos): lê com a MESMA leitura do
cálculo (rv.loader.PROCESSADORES) — o que passa aqui passa no cálculo — e devolve:

  erros   — o arquivo não serve (formato errado, coluna ausente...); o portal recusa o envio
  avisos  — o arquivo serve, mas vale conferir (ex.: parece ser de outro mês)
  resumo  — uma linha para quem enviou conferir se é o arquivo certo

Uso:
  python validar_arquivo.py --tipo coral --arquivo dma-pro-rata.csv --competencia 2026-09

Imprime uma linha de JSON no stdout. Só sai com código diferente de 0 se o próprio script quebrar.
"""

import argparse
import contextlib
import io
import json
from pathlib import Path

from rv.loader import PROCESSADORES, verificar_periodo_coral

_DICA_POR_TIPO = {
    "coral": "Esperadas: LOGIN, LOJA, PREMIAVEL, DIAS_NO_PERIODO e VALOR_VENDIDO_PRO_RATA.",
}


def _brl(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def _resumo(tipo: str, df) -> str:
    if tipo == "coral":
        return f"{len(df)} logins, {_brl(df['faturamento_realizado'].sum())} faturados"
    if tipo == "meta_faturamento":
        return f"{len(df)} metas em {df['unidade'].nunique()} lojas, total {_brl(df['meta_faturamento'].sum())}"
    if tipo == "colaboradores":
        return f"{len(df)} colaboradores"
    if tipo == "mapeamento":
        return f"{len(df)} logins"
    return f"{len(df)} lojas"


def _avisos_do_loader(texto: str) -> list[str]:
    """Os processadores avisam por print('[AVISO] ...'), com linhas de continuação sem o prefixo."""
    avisos: list[str] = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if linha.startswith("[AVISO]"):
            avisos.append(linha.removeprefix("[AVISO]").strip())
        elif avisos:
            avisos[-1] += " " + linha
    return avisos


def validar(tipo: str, caminho: str, competencia: str | None = None) -> dict:
    if tipo not in PROCESSADORES:
        return {"ok": False, "erros": [f"Tipo de arquivo desconhecido: '{tipo}'."], "avisos": [], "resumo": ""}

    leitor, proc = PROCESSADORES[tipo]
    capturado = io.StringIO()
    bruto = df = None
    try:
        with contextlib.redirect_stdout(capturado):
            bruto = leitor(Path(caminho))
            df = proc(bruto)
    except KeyError as e:
        erro = f"Coluna esperada não encontrada no arquivo: {e}. {_DICA_POR_TIPO.get(tipo, '')}".strip()
        return {"ok": False, "erros": [erro], "avisos": [], "resumo": ""}
    except Exception as e:  # leitura ou formato inválido: a mensagem do loader já é clara
        return {"ok": False, "erros": [str(e) or type(e).__name__], "avisos": [], "resumo": ""}

    if len(df) == 0:
        return {"ok": False, "erros": ["O arquivo não tem nenhuma linha válida."], "avisos": [], "resumo": ""}

    avisos = _avisos_do_loader(capturado.getvalue())
    if tipo == "coral" and competencia:
        avisos += verificar_periodo_coral(bruto, competencia)
    return {"ok": True, "erros": [], "avisos": avisos, "resumo": _resumo(tipo, df)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", required=True, choices=sorted(PROCESSADORES))
    parser.add_argument("--arquivo", required=True)
    parser.add_argument("--competencia", default=None, help="AAAA-MM; confere se o arquivo do Coral é desse mês")
    args = parser.parse_args()
    print(json.dumps(validar(args.tipo, args.arquivo, args.competencia)))


if __name__ == "__main__":
    main()

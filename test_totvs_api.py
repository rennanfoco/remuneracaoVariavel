"""
Testa a conexão com a API do TOTVS RM e imprime o retorno bruto da consulta API.04.
Uso: python test_totvs_api.py --mes 06 --ano 2026
"""

import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL  = os.getenv("TOTVS_RM_BASE_URL", "").rstrip("/")
USERNAME  = os.getenv("TOTVS_RM_USERNAME", "")
PASSWORD  = os.getenv("TOTVS_RM_PASSWORD", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", required=True, help="Mês (ex: 06)")
    parser.add_argument("--ano", required=True, help="Ano (ex: 2026)")
    parser.add_argument("--list-cargos", action="store_true",
                        help="Lista todos os cargos distintos (para preencher aba Cargos do referencias.xlsx)")
    args = parser.parse_args()

    if not all([BASE_URL, USERNAME, PASSWORD]):
        print("[ERRO] Variáveis de ambiente não carregadas. Verifique o .env.")
        sys.exit(1)

    url = f"{BASE_URL}/api/framework/v1/consultaSQLServer/RealizaConsulta/API.04/1/P/"
    params = {"parameters": f"MES={args.mes};ANO={args.ano}"}

    print(f"URL   : {url}")
    print(f"Params: {params}")
    print(f"User  : {USERNAME}\n")

    try:
        resp = requests.get(
            url,
            params=params,
            auth=(USERNAME, PASSWORD),
            verify=False,  # TOTVS cloud às vezes tem cert autoassinado
            timeout=30,
        )
    except requests.exceptions.ConnectionError as e:
        print(f"[ERRO] Não foi possível conectar: {e}")
        sys.exit(1)

    print(f"Status HTTP: {resp.status_code}")

    if resp.status_code != 200:
        print(f"Resposta:\n{resp.text[:2000]}")
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError:
        print(f"Resposta não é JSON:\n{resp.text[:2000]}")
        sys.exit(1)

    # Modo --list-cargos: apenas os cargos distintos
    if args.list_cargos:
        if isinstance(data, list) and data and "NOME1" in data[0]:
            cargos = sorted({r["NOME1"] for r in data if r.get("NOME1")})
            print(f"\n{len(cargos)} cargos distintos (campo NOME1):\n")
            for c in cargos:
                print(f"  {c}")
        else:
            print("Campo NOME1 não encontrado na resposta.")
        return

    # Imprime estrutura resumida
    if isinstance(data, list):
        print(f"\nRetornou {len(data)} registros.")
        if data:
            print(f"\nChaves do primeiro registro:\n  {list(data[0].keys())}")
            print(f"\nPrimeiros 3 registros:")
            print(json.dumps(data[:3], ensure_ascii=False, indent=2))
    elif isinstance(data, dict):
        print(f"\nRetornou um objeto dict. Chaves: {list(data.keys())}")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    else:
        print(f"\nTipo inesperado: {type(data)}")
        print(data)


if __name__ == "__main__":
    main()

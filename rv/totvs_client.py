"""
Cliente para a API REST do TOTVS RM.
Busca colaboradores direto do sistema, sem precisar de exportação manual.

Credenciais lidas do .env:
  TOTVS_RM_BASE_URL  — ex: https://focoaluguel164350.rm.cloudtotvs.com.br:8051
  TOTVS_RM_USERNAME  — usuário de integração
  TOTVS_RM_PASSWORD  — senha
"""

import os
import warnings

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = os.getenv("TOTVS_RM_BASE_URL", "").rstrip("/")
_USERNAME = os.getenv("TOTVS_RM_USERNAME", "")
_PASSWORD = os.getenv("TOTVS_RM_PASSWORD", "")

_RENOMEAR = {
    "CHAPA":            "matricula",
    "NOME":             "nome",
    "NOME1":            "cargo",
    "CC":               "unidade",
    "REGIONAL":         "regional",
    "SALARIO":          "salario_base",
    "DIAS_TRABALHADOS": "dias_trabalhados",
}


def buscar_colaboradores(mes: str, ano: str) -> pd.DataFrame:
    """
    Chama a consulta API.04 do TOTVS RM e retorna DataFrame normalizado,
    compatível com o que _proc_colaboradores() produziria a partir do CSV.

    Parâmetros:
      mes — número do mês com zero à esquerda (ex: "06")
      ano — ano com 4 dígitos (ex: "2026")
    """
    if not all([_BASE_URL, _USERNAME, _PASSWORD]):
        raise EnvironmentError(
            "Variáveis TOTVS_RM_BASE_URL, TOTVS_RM_USERNAME e TOTVS_RM_PASSWORD "
            "não encontradas. Verifique o arquivo .env."
        )

    from config import CARGOS_GRUPO, TOTVS_COD_COLIGADA

    url = f"{_BASE_URL}/api/framework/v1/consultaSQLServer/RealizaConsulta/API.04/{TOTVS_COD_COLIGADA}/P/"
    params = {"parameters": f"MES={mes};ANO={ano}"}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", requests.packages.urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(
            url,
            params=params,
            auth=(_USERNAME, _PASSWORD),
            verify=False,
            timeout=60,
        )

    resp.raise_for_status()

    registros = resp.json()
    if not registros:
        raise ValueError(f"API.04 retornou lista vazia para MES={mes} ANO={ano}.")

    df = pd.DataFrame(registros).rename(columns=_RENOMEAR)

    df["matricula"]        = df["matricula"].astype(str).str.strip()
    df["nome"]             = df["nome"].astype(str).str.strip()
    df["cargo"]            = df["cargo"].astype(str).str.strip().str.upper()
    df["unidade"]          = df["unidade"].astype(str).str.strip().str.upper()
    df["regional"]         = df["regional"].astype(str).str.strip().str.upper()
    df["salario_base"]     = pd.to_numeric(df["salario_base"], errors="coerce").fillna(0.0)
    df["dias_trabalhados"] = (
        pd.to_numeric(df["dias_trabalhados"], errors="coerce")
        .fillna(30).clip(0, 30).astype(int)
    )

    df["grupo_calculo"] = df["cargo"].map(CARGOS_GRUPO)
    sem_grupo = df[df["grupo_calculo"].isna()]
    if not sem_grupo.empty:
        cargos = sem_grupo["cargo"].unique().tolist()
        print(
            f"  [AVISO] Cargos sem grupo_calculo mapeado (receberão 'outros'): {cargos}\n"
            f"          Adicione esses cargos na aba 'Cargos' do referencias.xlsx."
        )
        df["grupo_calculo"] = df["grupo_calculo"].fillna("outros")

    return df

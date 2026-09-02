"""
Leitura e transformação de todos os arquivos de entrada do processo de RV.

Padrões de nome esperados na pasta de input (suportam glob):
  colaboradores_rm.csv           — extração do TOTVS RM (nome fixo)
  dma-accumulated*.csv           — dados brutos do Coral (DMA e faturamento são calculados aqui)
  data*.xlsx                     — NPS por atendente (agrega para nível de loja)
  Preventivas*.xlsx              — dados de manutenção preventiva por veículo
  Fechamento*.xlsx               — % conclusão Bate Pátio por loja
  Importação Planilha*.csv       — meta de faturamento por atendente (Controladoria)
  Lista de Logins*.xlsx          — mapeamento Login Coral → Matrícula RM
  nonrev*.xlsx                   — NONREV por loja (Área de Frotas) [opcional: aviso se ausente]

Cálculos realizados aqui:
  DMA = sum(VALOR VENDIDO where PREMIAVEL != 'no') / sum(DIAS where PREMIAVEL != 'no')
  faturamento_realizado = sum(VALOR VENDIDO) por login
  nps_loja = já vem agregado por Loja na origem — usa o valor direto
  preventiva_pct = campo '% Conformidade' da aba 'Análise de Preventivas' (bloco por loja),
                   já calculado pela área de Frotas — usa o valor direto
  bate_patio_pct = % POR LOJA * 100 (converte de fração para %)
"""

import unicodedata
from pathlib import Path
from typing import Optional
import pandas as pd

from config import CARGOS_GRUPO


def _normalizar_texto(s) -> str:
    """Remove acentos e normaliza para minúsculas (comparação tolerante a variações do arquivo)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.strip().lower()


# ---------------------------------------------------------------------------
# Padrões glob para localizar cada arquivo
# ---------------------------------------------------------------------------
PADROES = {
    "colaboradores":    "colaboradores_rm.csv",
    "coral":            "dma-accumulated*.csv",
    "nps":              "data*.xlsx",
    "preventiva":       "Preventivas*.xlsx",
    "bate_patio":       "Fechamento*.xlsx",
    "meta_faturamento": "Importa??o Planilha*.csv",
    "mapeamento":       "Lista de Logins*.xlsx",
    "nonrev":           "nonrev*.xlsx",          # opcional
}

# Arquivos sem os quais o processo não pode rodar
OBRIGATORIOS = {"colaboradores", "coral", "nps", "preventiva", "bate_patio",
                "meta_faturamento", "mapeamento"}


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _encontrar(input_dir: Path, padrao: str) -> Optional[Path]:
    """Encontra arquivo pelo padrão glob. Retorna None se não encontrado."""
    matches = sorted(input_dir.glob(padrao))
    if not matches:
        # Tenta padrão case-insensitive (Windows é case-insensitive, mas glob não é)
        matches = sorted(input_dir.glob(padrao.lower())) + sorted(input_dir.glob(padrao.upper()))
    if not matches:
        return None
    if len(matches) > 1:
        print(f"  [AVISO] Múltiplos arquivos para '{padrao}': {[m.name for m in matches]}. Usando: {matches[0].name}")
    return matches[0]


def _ler_csv(path: Path, **kwargs) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding=enc, dtype=str, **kwargs)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não foi possível determinar o encoding de '{path.name}'")


def _ler_xlsx(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_excel(path, dtype=str, **kwargs)


def _ler_xlsx_aba(path: Path, aba_alvo: str) -> pd.DataFrame:
    """Lê uma aba específica pelo nome (tolerante a acentos/maiúsculas), sem header fixo."""
    xls = pd.ExcelFile(path)
    aba = next((s for s in xls.sheet_names if _normalizar_texto(s) == _normalizar_texto(aba_alvo)), None)
    if aba is None:
        raise ValueError(
            f"Aba '{aba_alvo}' não encontrada em '{path.name}'. Abas disponíveis: {xls.sheet_names}"
        )
    return pd.read_excel(path, sheet_name=aba, header=None, dtype=str)


# ---------------------------------------------------------------------------
# Transformações por arquivo
# ---------------------------------------------------------------------------

def _proc_coral(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula DMA e faturamento_realizado por login a partir dos dados brutos do Coral.

    faturamento_realizado = sum(VALOR VENDIDO) por LOGIN
    dma = sum(VALOR VENDIDO | PREMIAVEL != 'no') / sum(DIAS | PREMIAVEL != 'no') por LOGIN

    Nota: cada contrato tem uma linha por item opcional (LDW, GNT, SLI, TOLL...).
    A coluna QTD_DIARIAS repete o total de diárias do contrato em toda linha —
    somá-la por login infla o denominador. A coluna DIAS só vem preenchida na
    linha do item base (LDW), contando os dias do contrato uma única vez.

    Retorna também dma_valor/dma_dias (numerador/denominador brutos por login) —
    necessários porque agregações acima do login (matrícula com múltiplos logins,
    unidade, regional) devem somar numerador e denominador e SÓ ENTÃO dividir.
    Tirar a média dos DMAs já calculados por login (média de razões) dá um
    resultado matematicamente diferente e incorreto.
    """
    df = df.copy()
    df.columns = [c.strip().upper() for c in df.columns]

    df["VALOR VENDIDO"] = pd.to_numeric(
        df["VALOR VENDIDO"].str.replace(",", "."), errors="coerce"
    ).fillna(0.0)
    df["DIAS"]        = pd.to_numeric(df["DIAS"], errors="coerce").fillna(0.0)
    df["PREMIAVEL"]   = df["PREMIAVEL"].str.strip().str.lower()
    df["LOGIN"]       = df["LOGIN"].str.strip().str.lower()
    df["LOJA"]        = df["LOJA"].str.strip().str.upper()

    fat = df.groupby("LOGIN", as_index=False)["VALOR VENDIDO"].sum()
    fat.columns = ["login_coral", "faturamento_realizado"]

    prem = df[df["PREMIAVEL"] != "no"]
    dma_valor = prem.groupby("LOGIN", as_index=False)["VALOR VENDIDO"].sum()
    dma_valor.columns = ["login_coral", "dma_valor"]
    dma_dias = prem.groupby("LOGIN", as_index=False)["DIAS"].sum()
    dma_dias.columns = ["login_coral", "dma_dias"]

    # loja principal por login (mais frequente)
    loja = (
        df.groupby("LOGIN")["LOJA"]
        .agg(lambda x: x.value_counts().index[0])
        .reset_index()
    )
    loja.columns = ["login_coral", "unidade"]

    result = (
        fat.merge(dma_valor, on="login_coral", how="left")
           .merge(dma_dias, on="login_coral", how="left")
           .merge(loja, on="login_coral", how="left")
    )
    result[["dma_valor", "dma_dias"]] = result[["dma_valor", "dma_dias"]].fillna(0.0)
    result["dma"] = (
        result["dma_valor"] / result["dma_dias"].replace(0, float("nan"))
    ).fillna(0.0)
    return result


def _proc_coral_por_loja(df: pd.DataFrame) -> pd.DataFrame:
    """
    Faturamento realizado por loja, atribuído pela loja do CONTRATO (coluna
    LOJA de cada linha do dma-accumulated) — não pela loja em que o
    colaborador está cadastrado no TOTVS. Usado no cálculo de Líderes,
    Gestores e Regionais; o faturamento individual do colaborador continua
    somando todas as suas transações independente da loja (ver _proc_coral).
    """
    df = df.copy()
    df.columns = [c.strip().upper() for c in df.columns]

    df["VALOR VENDIDO"] = pd.to_numeric(
        df["VALOR VENDIDO"].str.replace(",", "."), errors="coerce"
    ).fillna(0.0)
    df["LOJA"] = df["LOJA"].str.strip().str.upper()

    result = df.groupby("LOJA", as_index=False)["VALOR VENDIDO"].sum()
    result.columns = ["unidade", "fat_realizado_loja"]
    return result


def _proc_nps(df: pd.DataFrame) -> pd.DataFrame:
    """
    NPS por loja — já vem agregado na origem (uma linha por loja, valor direto).
    O arquivo tem linhas de cabeçalho (Ano/Mês) e um rodapé de filtros antes/depois
    do header real ('Loja' | 'NPS' | ...). O NPS do colaborador é o da sua unidade.
    """
    df = df.copy()
    df.columns = [str(c) for c in df.columns]

    header_row = None
    for i in range(len(df)):
        if any(str(v).strip().lower() == "loja" for v in df.iloc[i]):
            header_row = i
            break

    if header_row is None:
        raise ValueError("NPS: não encontrei coluna 'Loja' no arquivo.")

    df.columns = [str(v).strip() for v in df.iloc[header_row]]
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    col_loja = next((c for c in df.columns if c.strip().lower() == "loja"), None)
    col_nps  = next((c for c in df.columns if c.strip().lower() == "nps"), None)
    if not col_loja or not col_nps:
        raise ValueError(f"NPS: não encontrei colunas Loja e NPS. Disponíveis: {list(df.columns)}")

    result = df[[col_loja, col_nps]].copy()
    result.columns = ["unidade", "nps"]
    result["unidade"] = result["unidade"].astype(str).str.strip().str.upper()
    result["nps"] = pd.to_numeric(result["nps"].astype(str).str.replace(",", "."), errors="coerce")
    result = result.dropna(subset=["nps"])
    # Arredonda para inteiro (ex: 75,62 -> 76), conforme definido pelo usuário.
    result["nps"] = (result["nps"] + 0.5).apply(int).astype(float)
    return result


def _proc_preventiva(df: pd.DataFrame) -> pd.DataFrame:
    """
    % de conformidade de preventiva por loja.
    Lê o bloco 'ANÁLISE DETALHADA POR LOJA' da aba 'Análise de Preventivas':
    header com colunas 'Loja' e '% Conformidade', seguido de uma linha por loja
    e terminando numa linha 'TOTAL'. O valor já vem calculado pela área de
    Frotas — usado diretamente, sem recalcular.
    """
    df = df.copy()

    header_row = None
    for i in range(len(df)):
        valores = [_normalizar_texto(v) for v in df.iloc[i] if pd.notna(v)]
        if "loja" in valores and any("conformidade" in v for v in valores):
            header_row = i
            break

    if header_row is None:
        raise ValueError(
            "Preventivas: não encontrei o bloco com colunas 'Loja' e '% Conformidade' "
            "na aba 'Análise de Preventivas'."
        )

    header = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[header_row]]
    col_loja = next((i for i, v in enumerate(header) if _normalizar_texto(v) == "loja"), None)
    col_pct  = next((i for i, v in enumerate(header) if "conformidade" in _normalizar_texto(v)), None)

    if col_loja is None or col_pct is None:
        raise ValueError(f"Preventivas: colunas 'Loja'/'% Conformidade' não localizadas. Header: {header}")

    linhas = []
    for _, row in df.iloc[header_row + 1:].iterrows():
        loja = row.iloc[col_loja]
        if pd.isna(loja) or str(loja).strip().upper() == "TOTAL":
            break  # fim do bloco por loja

        pct = pd.to_numeric(str(row.iloc[col_pct]).replace(",", "."), errors="coerce")
        if pd.isna(pct):
            raise ValueError(
                f"Preventivas: '% Conformidade' ausente ou inválido para a loja '{loja}'. "
                f"Corrija o arquivo de origem antes de rodar o cálculo."
            )
        linhas.append({"unidade": str(loja).strip().upper(), "preventiva_pct": pct * 100})

    if not linhas:
        raise ValueError("Preventivas: nenhuma loja encontrada no bloco 'ANÁLISE DETALHADA POR LOJA'.")

    return pd.DataFrame(linhas)


def _proc_bate_patio(df: pd.DataFrame) -> pd.DataFrame:
    """
    % Conclusão Bate Pátio por loja — cruza a coluna 'FILIAL' (loja) com
    '% POR LOJA' (fração 0.0–1.0, convertida para %). O líder de pátio daquela
    loja é quem recebe essa nota no cálculo do indicador bate_patio.
    Valor ausente ou inválido vira 0% (não cancela o cálculo).
    """
    df = df.copy()
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    col_filial = next((c for c in df.columns if isinstance(c, str) and "filial" in c.lower()), None)
    col_pct    = next((c for c in df.columns if isinstance(c, str) and "% por loja" in c.lower()), None)

    if not col_filial or not col_pct:
        raise ValueError(
            f"Bate Pátio: não encontrei 'FILIAL' e '% POR LOJA'. Disponíveis: {list(df.columns)}"
        )

    result = df[[col_filial, col_pct]].copy()
    result[col_filial] = result[col_filial].astype(str).str.strip().str.upper()
    result[col_pct]    = pd.to_numeric(
        result[col_pct].astype(str).str.replace(",", "."), errors="coerce"
    ).fillna(0.0) * 100  # fração → %

    result.columns = ["unidade", "bate_patio_pct"]
    return result.dropna(subset=["unidade"])


def _proc_meta_faturamento(df: pd.DataFrame) -> pd.DataFrame:
    """
    Meta de faturamento por login (Controladoria).
    O arquivo contém uma linha extra de nomes de campo em inglês logo após o header.
    """
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Remove linha de nomes de campo em inglês (ex.: 'name', 'user_login', ...)
    primeira = df.iloc[0].astype(str).str.lower()
    if any(v in primeira.values for v in ("name", "user_login", "billing_goal")):
        df = df.iloc[1:].reset_index(drop=True)

    col_login = next(
        (c for c in df.columns if any(p in c.lower() for p in ("usu", "login", "usuario"))),
        None,
    )
    col_meta = next(
        (c for c in df.columns if "meta" in c.lower() and "fatur" in c.lower()),
        None,
    )

    if not col_login or not col_meta:
        raise ValueError(
            f"Meta Faturamento: não encontrei colunas de login e meta. Disponíveis: {list(df.columns)}"
        )

    result = df[[col_login, col_meta]].copy()
    result.columns = ["login_coral", "meta_faturamento"]
    result["login_coral"]     = result["login_coral"].str.strip().str.lower()
    result["meta_faturamento"] = pd.to_numeric(
        result["meta_faturamento"].str.replace(",", ".").str.replace(" ", ""),
        errors="coerce",
    ).fillna(0.0)
    return result.dropna(subset=["login_coral"])


def _proc_mapeamento(df: pd.DataFrame) -> pd.DataFrame:
    """Login Coral → Matrícula RM."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    col_login = next((c for c in df.columns if c.lower() in ("login", "login_coral")), None)
    col_mat   = next((c for c in df.columns if "matr" in c.lower()), None)

    if not col_login or not col_mat:
        raise ValueError(
            f"Mapeamento: não encontrei 'Login' e 'Matrícula'. Disponíveis: {list(df.columns)}"
        )

    result = df[[col_login, col_mat]].copy()
    result.columns = ["login_coral", "matricula"]
    result["login_coral"] = result["login_coral"].str.strip().str.lower()
    result["matricula"]   = result["matricula"].astype(str).str.strip()
    return result.dropna()


# O arquivo de Nonrev usa a nomenclatura própria da área de Frotas (códigos de
# 3 letras, sem o sufixo numérico do TOTVS). Mapeia para o código de loja (CC)
# usado no TOTVS RM. GRU/CGH são as duas lojas de São Paulo (Guarulhos/Congonhas).
_NONREV_PARA_TOTVS = {
    "GRU": "SAO10", "CGH": "SAO11",
    "AJU": "AJU10", "BPS": "BPS10", "CGR": "CGR10", "CNF": "CNF10",
    "CWB": "CWB10", "FLN": "FLN10", "FOR": "FOR10", "GIG": "GIG10",
    "GYN": "GYN10", "JPA": "JPA10", "MCZ": "MCZ10", "NAT": "NAT10",
    "NVT": "NVT10", "POA": "POA10", "QNS": "QNS10", "RAO": "RAO10",
    "REC": "REC20", "SDU": "SDU10", "SSA": "SSA10", "VCP": "VCP10",
    "VIX": "VIX10",
}


def _proc_nonrev(df: pd.DataFrame) -> pd.DataFrame:
    """
    NONREV por loja.
    O arquivo tem linhas de filtro no topo antes do header real ('Loja').
    O código da loja vem na nomenclatura da área de Frotas (ex: 'GIG') e é
    convertido para o código de loja do TOTVS (CC) via _NONREV_PARA_TOTVS.
    Valor vem em decimal (ex: 0.071 = 7.1%) — converte para %.
    Não tolera células vazias ou não numéricas — levanta erro se encontrar.
    """
    df = df.copy()
    df.columns = [str(c) for c in df.columns]

    # Localiza a linha onde a primeira coluna contém 'Loja'
    header_row = None
    for i, val in enumerate(df.iloc[:, 0]):
        if str(val).strip().lower() == "loja":
            header_row = i
            break

    if header_row is None:
        raise ValueError("NONREV: não encontrei coluna 'Loja' no arquivo.")

    # Reconstrói o DataFrame a partir da linha de header
    df.columns = [str(v).strip() for v in df.iloc[header_row]]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df = df.dropna(subset=[df.columns[0]])

    col_loja = df.columns[0]
    col_pct  = next((c for c in df.columns if "nonrev" in c.lower() or "%" in c.lower()), df.columns[1])

    result = df[[col_loja, col_pct]].copy()
    result.columns = ["unidade", "nonrev_pct"]
    result["unidade"] = result["unidade"].astype(str).str.strip().str.upper()

    nao_mapeados = sorted(set(result["unidade"]) - set(_NONREV_PARA_TOTVS))
    if nao_mapeados:
        raise ValueError(
            f"NONREV: códigos de loja sem mapeamento para o TOTVS: {nao_mapeados}. "
            f"Adicione-os em _NONREV_PARA_TOTVS (rv/loader.py)."
        )
    result["unidade"] = result["unidade"].map(_NONREV_PARA_TOTVS)

    pct_num = pd.to_numeric(result["nonrev_pct"].astype(str).str.replace(",", "."), errors="coerce")
    invalidos = result.loc[pct_num.isna(), "unidade"].tolist()
    if invalidos:
        raise ValueError(
            f"NONREV: valor ausente ou não numérico para as lojas: {invalidos}. "
            f"Corrija o arquivo de origem antes de rodar o cálculo."
        )
    result["nonrev_pct"] = pct_num * 100  # decimal → %

    return result


def _proc_colaboradores(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza DataFrame de colaboradores do TOTVS RM."""
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df["matricula"]        = df["matricula"].str.strip()
    df["nome"]             = df["nome"].str.strip()
    df["cargo"]            = df["cargo"].str.strip().str.upper()
    df["unidade"]          = df["unidade"].str.strip().str.upper()
    df["regional"]         = df["regional"].str.strip().str.upper()
    df["salario_base"]     = pd.to_numeric(
        df["salario_base"].str.replace(",", "."), errors="coerce"
    ).fillna(0.0)
    df["dias_trabalhados"] = pd.to_numeric(
        df["dias_trabalhados"], errors="coerce"
    ).fillna(30).clip(0, 30).astype(int)
    # grupo_calculo derivado do cargo via aba Cargos do referencias.xlsx
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


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

def carregar_tudo(
    input_dir: Path,
    colaboradores_df: pd.DataFrame = None,
) -> dict[str, pd.DataFrame]:
    """
    Localiza, lê e transforma todos os arquivos de input.
    Retorna dict com DataFrames prontos para o engine.
    Levanta FileNotFoundError se algum arquivo obrigatório não for encontrado.

    colaboradores_df — se fornecido, usa esse DataFrame no lugar de colaboradores_rm.csv
                       (útil quando os dados vêm direto da API do TOTVS RM).
    """
    encontrados: dict[str, Path] = {}
    ausentes: list[str] = []

    padroes    = {k: v for k, v in PADROES.items()    if not (colaboradores_df is not None and k == "colaboradores")}
    obrigat    = OBRIGATORIOS - ({"colaboradores"} if colaboradores_df is not None else set())

    for chave, padrao in padroes.items():
        path = _encontrar(input_dir, padrao)
        if path is None:
            if chave in obrigat:
                ausentes.append(f"{padrao}  (obrigatório)")
            else:
                print(f"  [AVISO] '{padrao}' não encontrado — grupos que dependem de NONREV receberão 0.")
        else:
            encontrados[chave] = path
            print(f"  {chave:<20} : {path.name}")

    if ausentes:
        raise FileNotFoundError(
            f"Arquivos obrigatórios não encontrados em '{input_dir}':\n  "
            + "\n  ".join(ausentes)
        )

    def _ler_xlsx_sem_header(path: Path) -> pd.DataFrame:
        return pd.read_excel(path, header=None, dtype=str)

    def _ler_preventiva(path: Path) -> pd.DataFrame:
        return _ler_xlsx_aba(path, "Análise de Preventivas")

    processadores = {
        "colaboradores":    (_ler_csv,              _proc_colaboradores),
        "coral":            (_ler_csv,              _proc_coral),
        "nps":              (_ler_xlsx_sem_header,  _proc_nps),
        "preventiva":       (_ler_preventiva,       _proc_preventiva),
        "bate_patio":       (_ler_xlsx,             _proc_bate_patio),
        "meta_faturamento": (_ler_csv,              _proc_meta_faturamento),
        "mapeamento":       (_ler_xlsx,             _proc_mapeamento),
        "nonrev":           (_ler_xlsx_sem_header,  _proc_nonrev),
    }

    data: dict[str, pd.DataFrame] = {}

    if colaboradores_df is not None:
        data["colaboradores"] = colaboradores_df
        print(f"  {'colaboradores':<20} : via API TOTVS RM ({len(colaboradores_df)} registros)")

    for chave, path in encontrados.items():
        leitor, proc = processadores[chave]
        raw = leitor(path)
        data[chave] = proc(raw)
        if chave == "coral":
            # Faturamento por loja do contrato (não pela loja do colaborador) —
            # usado no cálculo de Líderes, Gestores e Regionais.
            data["coral_por_loja"] = _proc_coral_por_loja(raw)

    # NONREV ausente: DataFrame vazio com colunas mínimas para o engine não quebrar
    if "nonrev" not in data:
        data["nonrev"] = pd.DataFrame(columns=["unidade", "nonrev_pct"])

    return data


# Mantém compatibilidade com engine.py que chama normalizar_colaboradores
def normalizar_colaboradores(df: pd.DataFrame) -> pd.DataFrame:
    return df  # já processado em _proc_colaboradores

"""
Regras de negócio do cálculo de RV no portal: o "status atual" dos arquivos de uma competência
(aba Arquivos), a validação no envio, a busca de colaboradores no TOTVS e a execução do cálculo
(aba Cálculo).

Por quê subprocess para o motor (cálculo, validação e busca no TOTVS): config.py carrega as regras
como constantes no import do módulo (`from config import REGRAS, TETOS, ...`). Num processo web de
longa duração, isso significa que editar uma regra pelo admin não teria efeito até reiniciar o
servidor. Rodar o motor como subprocesso cria um processo Python novo a cada uso — import sempre
fresco — sem precisar alterar rv/*, config.py ou main.py (além do REFERENCIAS_XLSX_PATH, ver
config.py). Cada uso exporta as regras vigentes do banco para um referencias.xlsx temporário.
"""

import datetime
import io
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from .models import (
    TIPO_ARQUIVO_CHOICES, TIPOS_HERDADOS_DA_COMPETENCIA_ANTERIOR, TIPOS_OBRIGATORIOS,
    ArquivoCompetencia, ExecucaoCalculo,
)

# Nome de arquivo canônico esperado por rv.loader.PADROES para cada tipo.
NOME_CANONICO_POR_TIPO = {
    "colaboradores": "colaboradores_rm.csv",
    "coral": "dma-pro-rata.csv",
    "nps": "data.xlsx",
    "preventiva": "Preventivas.xlsx",
    "bate_patio": "Fechamento.xlsx",
    "nonrev": "nonrev.xlsx",
    "meta_faturamento": "Importação Planilha.csv",
    "mapeamento": "Lista de Logins.xlsx",
}

# O arquivo de metas pode vir como "Base metas" (xlsx, formato atual) ou "Importação Planilha"
# (csv, formato antigo) — o loader escolhe como ler pela extensão.
NOME_CANONICO_META_XLSX = "Base metas.xlsx"

TIMEOUT_SEGUNDOS = 180
TIMEOUT_TOTVS_SEGUNDOS = 90
TIMEOUT_VALIDACAO_SEGUNDOS = 120


def nome_canonico(tipo: str, nome_do_arquivo: str) -> str:
    if tipo == "meta_faturamento" and nome_do_arquivo.lower().endswith(".xlsx"):
        return NOME_CANONICO_META_XLSX
    return NOME_CANONICO_POR_TIPO[tipo]


class ErroTotvs(Exception):
    """Não foi possível buscar os colaboradores no TOTVS (fora do ar, credencial recusada, demora...)."""


class CalculoBloqueado(Exception):
    """A competência não tem tudo o que o cálculo exige; `pendencias` diz o que falta."""

    def __init__(self, pendencias: list[str]):
        super().__init__("; ".join(pendencias))
        self.pendencias = pendencias


# ---------------------------------------------------------------------------
# Status atual dos arquivos de uma competência
# ---------------------------------------------------------------------------

@dataclass
class ItemDaCompetencia:
    tipo: str
    rotulo: str
    obrigatorio: bool
    arquivo: ArquivoCompetencia | None
    herdado: bool  # veio de uma competência anterior (só a lista de logins)
    buscar_agora: bool  # será buscado no TOTVS no cálculo
    pendencia: str

    @property
    def ok(self) -> bool:
        return not self.pendencia


@dataclass
class Situacao:
    competencia: str
    itens: list[ItemDaCompetencia]

    @property
    def pendencias(self) -> list[str]:
        return [i.pendencia for i in self.itens if i.pendencia]

    @property
    def pode_calcular(self) -> bool:
        return not self.pendencias

    @property
    def arquivos(self) -> list[ArquivoCompetencia]:
        return [i.arquivo for i in self.itens if i.arquivo is not None]


def situacao_da_competencia(competencia: str, buscar_totvs: bool = False) -> Situacao:
    """
    O que o cálculo usaria hoje para esta competência: a versão mais recente de cada tipo.
    Colaboradores são sempre DA competência (dias trabalhados e lista de ativos mudam todo mês),
    venham do TOTVS ou de um CSV — vale o que aconteceu por último. Já a lista de logins, se a
    competência não tem uma, herda a da competência anterior mais recente.
    """
    itens = []
    for tipo, rotulo in TIPO_ARQUIVO_CHOICES:
        arquivo = ArquivoCompetencia.objects.filter(competencia=competencia, tipo=tipo).first()
        herdado = False
        if arquivo is None and tipo in TIPOS_HERDADOS_DA_COMPETENCIA_ANTERIOR:
            arquivo = (
                ArquivoCompetencia.objects.filter(competencia__lt=competencia, tipo=tipo)
                .order_by("-competencia", "-enviado_em", "-id").first()
            )
            herdado = arquivo is not None

        obrigatorio = tipo in TIPOS_OBRIGATORIOS
        buscar_agora = tipo == "colaboradores" and buscar_totvs
        pendencia = ""
        if obrigatorio and arquivo is None and not buscar_agora:
            if tipo == "colaboradores":
                pendencia = (
                    f"Não há base de colaboradores da competência {competencia}. Marque "
                    f"\"Buscar colaboradores no TOTVS agora\" ou envie o CSV na aba Arquivos."
                )
            else:
                pendencia = f"Falta o arquivo \"{rotulo}\" da competência {competencia}."
        itens.append(ItemDaCompetencia(tipo, rotulo, obrigatorio, arquivo, herdado, buscar_agora, pendencia))
    return Situacao(competencia, itens)


def competencia_padrao() -> str:
    """A competência mais recente que já tem arquivos; senão, o mês anterior (a folha fecha no mês seguinte)."""
    ultima = ArquivoCompetencia.objects.order_by("-competencia").values_list("competencia", flat=True).first()
    if ultima:
        return ultima
    mes_anterior = timezone.localdate().replace(day=1) - datetime.timedelta(days=1)
    return mes_anterior.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Rodar scripts do motor (processo novo, com as regras vigentes do banco)
# ---------------------------------------------------------------------------

def _exportar_referencias(pasta: str) -> Path:
    caminho = Path(pasta) / "referencias.xlsx"
    call_command("exportar_referencias", saida=str(caminho), stdout=io.StringIO())
    return caminho


def _rodar_script(script: str, args: list[str], referencias: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [settings.LEGACY_PYTHON_EXECUTABLE, str(settings.MOTOR_CALCULO_DIR / script), *args],
        cwd=str(settings.MOTOR_CALCULO_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "REFERENCIAS_XLSX_PATH": str(referencias)},
    )


def _ultima_linha(texto: str) -> str:
    linhas = [l.strip() for l in (texto or "").strip().splitlines() if l.strip()]
    return linhas[-1] if linhas else ""


# ---------------------------------------------------------------------------
# Aba Arquivos: validar e registrar o que foi enviado
# ---------------------------------------------------------------------------

def validar_arquivo(tipo: str, arquivo_upload, competencia: str) -> dict:
    """
    Lê o arquivo com a mesma leitura do cálculo (motor_calculo/validar_arquivo.py) e devolve
    {"ok", "erros", "avisos", "resumo"}. Erro = o arquivo não será guardado.
    """
    def falha(msg: str) -> dict:
        return {"ok": False, "erros": [msg], "avisos": [], "resumo": ""}

    with tempfile.TemporaryDirectory(prefix="rv_validar_", ignore_cleanup_errors=True) as tmp:
        caminho = Path(tmp) / f"arquivo{Path(arquivo_upload.name).suffix.lower()}"
        with open(caminho, "wb") as f:
            for chunk in arquivo_upload.chunks():
                f.write(chunk)
        arquivo_upload.seek(0)

        referencias = _exportar_referencias(tmp)
        try:
            r = _rodar_script(
                "validar_arquivo.py",
                ["--tipo", tipo, "--arquivo", str(caminho), "--competencia", competencia],
                referencias, TIMEOUT_VALIDACAO_SEGUNDOS,
            )
        except subprocess.TimeoutExpired:
            return falha("A leitura do arquivo demorou demais. Confira se é o arquivo certo e tente de novo.")

    if r.returncode != 0:
        return falha(_ultima_linha(r.stderr) or "Não foi possível ler o arquivo.")
    try:
        return json.loads(_ultima_linha(r.stdout))
    except ValueError:
        return falha("O validador devolveu uma resposta inesperada.")


def registrar_arquivo(competencia: str, tipo: str, arquivo_upload, usuario, validacao: dict) -> ArquivoCompetencia:
    return ArquivoCompetencia.objects.create(
        competencia=competencia,
        tipo=tipo,
        arquivo=arquivo_upload,
        nome_original=arquivo_upload.name,
        origem="upload",
        enviado_por=usuario,
        resumo=validacao.get("resumo", ""),
        avisos="\n".join(validacao.get("avisos", [])),
    )


# ---------------------------------------------------------------------------
# Aba Cálculo: buscar colaboradores no TOTVS e calcular
# ---------------------------------------------------------------------------

def buscar_colaboradores_totvs(competencia: str, usuario) -> ArquivoCompetencia:
    """
    Busca os colaboradores da competência no TOTVS (API.04) e guarda o resultado como a base de
    colaboradores dela — uma foto do momento da busca, que os próximos cálculos podem reutilizar.
    """
    with tempfile.TemporaryDirectory(prefix="rv_totvs_", ignore_cleanup_errors=True) as tmp:
        referencias = _exportar_referencias(tmp)
        saida = Path(tmp) / "colaboradores_rm.csv"
        try:
            r = _rodar_script(
                "exportar_colaboradores.py", ["--competencia", competencia, "--saida", str(saida)],
                referencias, TIMEOUT_TOTVS_SEGUNDOS,
            )
        except subprocess.TimeoutExpired:
            raise ErroTotvs("O TOTVS demorou demais para responder. Tente de novo em alguns minutos.")
        if r.returncode != 0 or not saida.exists():
            motivo = _ultima_linha(r.stderr).removeprefix("[ERRO]").strip()
            raise ErroTotvs(f"Não foi possível buscar os colaboradores no TOTVS: {motivo or 'sem detalhes'}.")
        conteudo = saida.read_bytes()
        resumo = _ultima_linha(r.stdout).split(" gravados")[0]

    nome = f"colaboradores_totvs_{competencia}.csv"
    arquivo = ArquivoCompetencia(
        competencia=competencia, tipo="colaboradores", nome_original=nome, origem="totvs",
        enviado_por=usuario, resumo=resumo,
    )
    arquivo.arquivo.save(nome, ContentFile(conteudo))
    return arquivo


def iniciar_calculo(competencia: str, usuario, buscar_totvs: bool = False) -> ExecucaoCalculo:
    """
    Calcula a competência com o status atual dos arquivos. Levanta CalculoBloqueado se faltar algo
    (inclusive base de colaboradores da competência, quando não se pede para buscar no TOTVS) e
    ErroTotvs se a busca falhar — nos dois casos nenhuma execução é criada.
    """
    situacao = situacao_da_competencia(competencia, buscar_totvs)
    if not situacao.pode_calcular:
        raise CalculoBloqueado(situacao.pendencias)

    if buscar_totvs:
        buscar_colaboradores_totvs(competencia, usuario)
        situacao = situacao_da_competencia(competencia)

    execucao = ExecucaoCalculo.objects.create(
        competencia=competencia, usar_api_totvs=buscar_totvs, iniciado_por=usuario,
    )
    execucao.arquivos_usados.set(situacao.arquivos)
    executar_calculo(execucao)
    return execucao


def executar_calculo(execucao: ExecucaoCalculo) -> None:
    """
    Roda o cálculo para a ExecucaoCalculo já criada (com seus arquivos_usados definidos) e atualiza
    o próprio registro com o resultado (status, log, arquivos gerados ou mensagem de erro). Não
    levanta exceção — qualquer falha é capturada e registrada na própria execução.
    """
    with tempfile.TemporaryDirectory(prefix="rv_referencias_") as tmp_regras, \
         tempfile.TemporaryDirectory(prefix="rv_input_") as tmp_input, \
         tempfile.TemporaryDirectory(prefix="rv_output_") as tmp_output:

        referencias_path = Path(tmp_regras) / "referencias.xlsx"
        call_command("exportar_referencias", saida=str(referencias_path), stdout=io.StringIO())

        for versao in execucao.arquivos_usados.all():
            destino = Path(tmp_input) / nome_canonico(versao.tipo, versao.nome_original)
            with versao.arquivo.open("rb") as origem, open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida)

        comando = [
            settings.LEGACY_PYTHON_EXECUTABLE, str(settings.LEGACY_MAIN_SCRIPT),
            "--competencia", execucao.competencia,
            "--input", tmp_input,
            "--output", tmp_output,
        ]

        try:
            resultado = subprocess.run(
                comando,
                cwd=str(settings.MOTOR_CALCULO_DIR),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SEGUNDOS,
                env={**os.environ, "REFERENCIAS_XLSX_PATH": str(referencias_path)},
            )
        except subprocess.TimeoutExpired:
            execucao.status = "erro"
            execucao.erro_mensagem = f"O cálculo excedeu o tempo limite de {TIMEOUT_SEGUNDOS}s."
            execucao.concluido_em = timezone.now()
            execucao.save()
            return

        execucao.log = resultado.stdout

        if resultado.returncode != 0:
            execucao.status = "erro"
            execucao.erro_mensagem = _mensagem_de_erro(resultado)
            execucao.concluido_em = timezone.now()
            execucao.save()
            return

        txt_path = _unico_arquivo(Path(tmp_output), "*.txt")
        relatorio_path = _unico_arquivo(Path(tmp_output), "*_relatorio.xlsx")

        if txt_path:
            with open(txt_path, "rb") as f:
                execucao.arquivo_txt.save(txt_path.name, ContentFile(f.read()), save=False)
        if relatorio_path:
            with open(relatorio_path, "rb") as f:
                execucao.arquivo_relatorio.save(relatorio_path.name, ContentFile(f.read()), save=False)

        execucao.status = "concluido"
        execucao.concluido_em = timezone.now()
        execucao.save()


def _mensagem_de_erro(resultado: subprocess.CompletedProcess) -> str:
    """
    O motor avisa os erros de dados/regras com "[ERRO] ..." na saída normal e sai com código 1 (stderr
    só tem conteúdo quando o Python quebra) — sem isto a tela mostraria "sem mensagem detalhada"
    para erros que dizem exatamente o que corrigir (ex: meta mensal de NPS não cadastrada).
    """
    if resultado.stderr and resultado.stderr.strip():
        return resultado.stderr
    linhas = (resultado.stdout or "").splitlines()
    for i in range(len(linhas) - 1, -1, -1):
        if linhas[i].strip().startswith("[ERRO]"):
            texto = "\n".join(linhas[i:]).strip()
            return texto.removeprefix("[ERRO]").strip()
    return "Processo encerrou com erro, sem mensagem detalhada."


def _unico_arquivo(diretorio: Path, padrao: str) -> Path | None:
    encontrados = sorted(diretorio.glob(padrao))
    return encontrados[0] if encontrados else None

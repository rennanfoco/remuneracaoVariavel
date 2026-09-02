"""
Orquestra uma execução de cálculo de RV chamando main.py via subprocess.

Por quê subprocess (e não importar rv.engine/rv.loader direto no processo
Django): config.py carrega as regras como constantes no import do módulo
(`from config import REGRAS, TETOS, ...`). Num processo web de longa duração,
isso significa que editar uma regra pelo admin não teria efeito até reiniciar
o servidor. Rodar main.py como subprocesso cria um processo Python novo a
cada execução — import sempre fresco — sem precisar alterar rv/*, config.py
ou main.py (além do REFERENCIAS_XLSX_PATH, ver config.py).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from .models import ExecucaoCalculo

# Nome de arquivo canônico esperado por rv.loader.PADROES para cada tipo.
NOME_CANONICO_POR_TIPO = {
    "colaboradores": "colaboradores_rm.csv",
    "coral": "dma-accumulated.csv",
    "nps": "data.xlsx",
    "preventiva": "Preventivas.xlsx",
    "bate_patio": "Fechamento.xlsx",
    "nonrev": "nonrev.xlsx",
    "meta_faturamento": "Importação Planilha.csv",
    "mapeamento": "Lista de Logins.xlsx",
}

TIMEOUT_SEGUNDOS = 180


def executar_calculo(execucao: ExecucaoCalculo) -> None:
    """
    Roda o cálculo para a ExecucaoCalculo já criada (com seus ArquivoUpload
    já salvos) e atualiza o próprio registro com o resultado (status, log,
    arquivos gerados ou mensagem de erro). Não levanta exceção — qualquer
    falha é capturada e registrada na própria execução.
    """
    with tempfile.TemporaryDirectory(prefix="rv_referencias_") as tmp_regras, \
         tempfile.TemporaryDirectory(prefix="rv_input_") as tmp_input, \
         tempfile.TemporaryDirectory(prefix="rv_output_") as tmp_output:

        referencias_path = Path(tmp_regras) / "referencias.xlsx"
        call_command("exportar_referencias", saida=str(referencias_path))

        for upload in execucao.arquivos.all():
            nome_canonico = NOME_CANONICO_POR_TIPO[upload.tipo]
            destino = Path(tmp_input) / nome_canonico
            with upload.arquivo.open("rb") as origem, open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida)

        comando = [
            settings.LEGACY_PYTHON_EXECUTABLE, str(settings.LEGACY_MAIN_SCRIPT),
            "--competencia", execucao.competencia,
            "--input", tmp_input,
            "--output", tmp_output,
        ]
        if execucao.usar_api_totvs:
            comando.append("--api")

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
            execucao.erro_mensagem = resultado.stderr or "Processo encerrou com erro, sem mensagem detalhada."
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


def _unico_arquivo(diretorio: Path, padrao: str) -> Path | None:
    encontrados = sorted(diretorio.glob(padrao))
    return encontrados[0] if encontrados else None

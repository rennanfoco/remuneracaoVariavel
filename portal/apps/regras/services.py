"""
Orquestra as ações de regras de negócio disparadas pela tela (não pelo
terminal): importar uma planilha registrando o lote, e reverter/reaplicar
uma importação inteira de uma vez — ver ImportacaoReferencias em models.py
pra entender o mecanismo.
"""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from .models import MODELOS_VERSIONADOS, ImportacaoReferencias


def importar_planilha(arquivo_upload, usuario) -> ImportacaoReferencias:
    """
    Salva o arquivo enviado num caminho temporário, roda o comando
    importar_referencias (que já marca cada mudança com um lote), e
    registra essa importação — usada pela view de upload.
    """
    # ignore_cleanup_errors: segurança extra pro Windows, caso algum handle de
    # arquivo fique aberto por mais tempo do que deveria — nunca falha a
    # importação por causa de limpeza de diretório temporário.
    with tempfile.TemporaryDirectory(prefix="rv_import_", ignore_cleanup_errors=True) as tmp_dir:
        caminho = Path(tmp_dir) / arquivo_upload.name
        with open(caminho, "wb") as f:
            for chunk in arquivo_upload.chunks():
                f.write(chunk)

        from apps.regras.management.commands.importar_referencias import Command
        comando = Command()
        resumo = comando.handle(arquivo=str(caminho), lote=None)

    return ImportacaoReferencias.objects.create(
        arquivo_nome=arquivo_upload.name,
        importado_por=usuario,
        identificador_lote=comando.lote,
        resumo=resumo,
        status="aplicada",
    )


def exportar_planilha(caminho_destino: str) -> None:
    """Gera um referencias.xlsx no caminho dado, com o estado atual do banco."""
    call_command("exportar_referencias", saida=caminho_destino)


@transaction.atomic
def reverter_importacao(importacao: ImportacaoReferencias, usuario) -> list[str]:
    """
    Restaura todo registro tocado por esta importação ao estado imediatamente
    ANTERIOR a ela (ou apaga, se a importação tiver criado o registro).
    Retorna a lista de avisos (ex: registro que não pôde ser apagado por
    estar referenciado em outro lugar).
    """
    if importacao.status == "revertida":
        return ["Esta importação já está revertida."]
    avisos = _restaurar_lote(importacao.identificador_lote, para_estado_anterior=True)
    importacao.status = "revertida"
    importacao.alterado_por = usuario
    importacao.alterado_em = timezone.now()
    importacao.save()
    return avisos


@transaction.atomic
def reaplicar_importacao(importacao: ImportacaoReferencias, usuario) -> list[str]:
    """Inverso de reverter_importacao — restaura o snapshot desta própria importação."""
    if importacao.status == "aplicada":
        return ["Esta importação já está aplicada."]
    avisos = _restaurar_lote(importacao.identificador_lote, para_estado_anterior=False)
    importacao.status = "aplicada"
    importacao.alterado_por = usuario
    importacao.alterado_em = timezone.now()
    importacao.save()
    return avisos


def _restaurar_lote(lote: str, para_estado_anterior: bool) -> list[str]:
    avisos = []
    for modelo in MODELOS_VERSIONADOS:
        historicos = modelo.history.filter(history_change_reason=lote)
        for hist in historicos:
            if para_estado_anterior:
                anterior = hist.prev_record
                if anterior is None:
                    # esta importação CRIOU o registro -> reverter = apagar
                    try:
                        modelo.objects.filter(pk=hist.instance.pk).delete()
                    except Exception as e:  # ex: ProtectedError se algo mais referencia o registro
                        avisos.append(
                            f"Não foi possível remover {modelo.__name__} #{hist.instance.pk} ({e})."
                        )
                else:
                    anterior.instance.save()
            else:
                # reaplicar: restaura o snapshot da PRÓPRIA importação (recria
                # o registro se ele tiver sido apagado por um revert anterior)
                hist.instance.save()
    return avisos

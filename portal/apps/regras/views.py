import tempfile
from functools import wraps
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.utils import e_admin_rv

from . import services
from .models import (
    Cargo, Grupo, ImportacaoReferencias, IndicadorRegra, Loja,
    MetaFaturamentoRegional, MetaMensal, ParametroTOTVS,
)


def admin_rv_required(view_func):
    """Bloqueia quem não é superusuário nem membro do grupo Gestão RV —
    diferente de @staff_member_required, não depende de is_staff (usuário
    comum nunca tem is_staff, mas essa checagem é sobre o papel, não o admin)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not e_admin_rv(request.user):
            return HttpResponseForbidden("Só quem é do grupo Gestão RV pode acessar esta página.")
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
def visualizar(request):
    context = {
        "e_admin": e_admin_rv(request.user),
        "grupos": Grupo.objects.order_by("nome"),
        "cargos": Cargo.objects.select_related("grupo").order_by("nome"),
        "indicadores": (
            IndicadorRegra.objects
            .select_related("grupo")
            .prefetch_related("faixas")
            .order_by("grupo__nome", "indicador")
        ),
        "metas_mensais": MetaMensal.objects.order_by("-mes", "chave", "faixa"),
        "metas_fat_regional": MetaFaturamentoRegional.objects.order_by("-mes", "regional"),
        "lojas": Loja.objects.order_by("regional", "unidade"),
        "totvs": ParametroTOTVS.objects.order_by("parametro"),
    }
    return render(request, "regras/visualizar.html", context)


@login_required
def exportar(request):
    with tempfile.TemporaryDirectory(prefix="rv_export_") as tmp_dir:
        caminho = Path(tmp_dir) / "referencias_exportado.xlsx"
        services.exportar_planilha(str(caminho))
        # FileResponse precisa do arquivo aberto além do fim do `with` — lê
        # os bytes antes do diretório temporário ser removido.
        conteudo = caminho.read_bytes()

    from django.http import HttpResponse
    resposta = HttpResponse(
        conteudo,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resposta["Content-Disposition"] = 'attachment; filename="referencias_exportado.xlsx"'
    return resposta


@admin_rv_required
def importar(request):
    if request.method == "POST":
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            messages.error(request, "Selecione um arquivo .xlsx antes de importar.")
        else:
            try:
                importacao = services.importar_planilha(arquivo, request.user)
                messages.success(
                    request,
                    f"Importado com sucesso ({importacao.resumo}). "
                    f"Se algo saiu errado, você pode reverter em Histórico de Importações.",
                )
                return redirect("regras:historico_importacoes")
            except Exception as e:
                messages.error(request, f"Falha ao importar: {e}")
    return render(request, "regras/importar.html")


@admin_rv_required
def historico_importacoes(request):
    importacoes = ImportacaoReferencias.objects.select_related("importado_por", "alterado_por").all()
    return render(request, "regras/historico_importacoes.html", {"importacoes": importacoes})


@admin_rv_required
def reverter(request, pk):
    importacao = get_object_or_404(ImportacaoReferencias, pk=pk)
    if request.method == "POST":
        avisos = services.reverter_importacao(importacao, request.user)
        if avisos:
            messages.warning(request, "Revertido com avisos: " + " | ".join(avisos))
        else:
            messages.success(request, f"Importação de {importacao.arquivo_nome} revertida.")
    return redirect("regras:historico_importacoes")


@admin_rv_required
def reaplicar(request, pk):
    importacao = get_object_or_404(ImportacaoReferencias, pk=pk)
    if request.method == "POST":
        avisos = services.reaplicar_importacao(importacao, request.user)
        if avisos:
            messages.warning(request, "Reaplicado com avisos: " + " | ".join(avisos))
        else:
            messages.success(request, f"Importação de {importacao.arquivo_nome} reaplicada.")
    return redirect("regras:historico_importacoes")

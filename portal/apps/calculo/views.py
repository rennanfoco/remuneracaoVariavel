import pandas as pd
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CAMPOS_ARQUIVO, ExecutarCalculoForm
from .models import ArquivoUpload, ExecucaoCalculo
from .services import executar_calculo


@login_required
def executar(request):
    if request.method == "POST":
        form = ExecutarCalculoForm(request.POST, request.FILES)
        if form.is_valid():
            execucao = ExecucaoCalculo.objects.create(
                competencia=form.cleaned_data["competencia"],
                usar_api_totvs=form.cleaned_data["usar_api_totvs"],
                iniciado_por=request.user,
            )
            for tipo, _rotulo, _obrigatorio in CAMPOS_ARQUIVO:
                arquivo = form.cleaned_data.get(tipo)
                if arquivo:
                    ArquivoUpload.objects.create(execucao=execucao, tipo=tipo, arquivo=arquivo)

            # Síncrono: ~660 linhas processam em segundos, dentro de um
            # timeout de requisição razoável — ver services.TIMEOUT_SEGUNDOS.
            executar_calculo(execucao)
            return redirect("calculo:resultado", pk=execucao.pk)
    else:
        form = ExecutarCalculoForm()

    return render(request, "calculo/executar.html", {"form": form})


@login_required
def resultado(request, pk):
    execucao = get_object_or_404(ExecucaoCalculo, pk=pk)
    relatorio = _ler_relatorio(execucao)
    return render(request, "calculo/resultado.html", {"execucao": execucao, "relatorio": relatorio})


@login_required
def historico(request):
    execucoes = ExecucaoCalculo.objects.select_related("iniciado_por").all()[:100]
    return render(request, "calculo/historico.html", {"execucoes": execucoes})


# ---------------------------------------------------------------------------
# Leitura do relatório gerado, pra visualização na tela (sem precisar baixar
# o Excel) — lê o mesmo arquivo .xlsx que o botão de download oferece,
# nenhum dado novo é calculado aqui. Ver rv/output.py::gerar_relatorio.
# ---------------------------------------------------------------------------

def _fmt_moeda(v: float) -> str:
    texto = f"{v:,.2f}"                                    # "1,234.56" (padrão Python)
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")  # "1.234,56" (padrão BR)
    return f"R$ {texto}"


def _fmt_pct(v: float, casas: int = 1) -> str:
    texto = f"{v:,.{casas}f}".replace(".", ",")
    return f"{texto}%"


def _fmt_numero(v: float, casas: int = 1) -> str:
    texto = f"{v:,.{casas}f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return texto


def _formatar_celula(coluna: str, valor) -> dict:
    """Retorna {"texto": str exibido, "ord": valor usado pra ordenar na tela}."""
    if pd.isna(valor):
        return {"texto": "—", "ord": ""}
    if coluna.endswith("(R$)"):
        return {"texto": _fmt_moeda(float(valor)), "ord": float(valor)}
    if coluna.startswith("Multiplicador"):
        pct = float(valor) * 100
        return {"texto": _fmt_pct(pct), "ord": pct}
    if "(%" in coluna or "Atingimento" in coluna:
        return {"texto": _fmt_pct(float(valor)), "ord": float(valor)}
    if coluna == "Elegível":
        return {"texto": "Sim" if valor else "Não", "ord": 1 if valor else 0}
    if coluna in ("DMA", "NPS"):
        return {"texto": _fmt_numero(float(valor)), "ord": float(valor)}
    if coluna == "Dias Trabalhados":
        return {"texto": str(int(valor)), "ord": int(valor)}
    return {"texto": str(valor), "ord": str(valor).lower()}


def _ler_relatorio(execucao: ExecucaoCalculo) -> dict | None:
    """
    Lê o relatório .xlsx já gerado e monta os 3 níveis de visualização:
    totais gerais, resumo por grupo, e a tabela detalhada por colaborador.
    Retorna None se a execução não tiver relatório (erro, processando, ou
    o arquivo não puder ser lido) — a tela cai de volta pro estado sem
    visualização, sem quebrar a página.
    """
    if execucao.status != "concluido" or not execucao.arquivo_relatorio:
        return None

    try:
        planilhas = pd.read_excel(
            execucao.arquivo_relatorio.path,
            sheet_name=["Detalhado", "Resumo por Grupo"],
        )
    except Exception:
        return None

    detalhado = planilhas["Detalhado"]
    resumo = planilhas["Resumo por Grupo"]

    processados = int(resumo["Total"].sum())
    elegiveis   = int(resumo["Elegíveis"].sum())
    com_premio  = int(resumo["Com_Prêmio"].sum())
    resumo_geral = {
        "processados":  processados,
        "elegiveis":    elegiveis,
        "com_premio":   com_premio,
        "sem_premio":   elegiveis - com_premio,
        "inelegiveis":  processados - elegiveis,
        "valor_total":  _fmt_moeda(float(resumo["Valor_Total_RV"].sum())),
    }

    resumo_grupo = [
        {
            "grupo":         row["Grupo RV"],
            "total":         int(row["Total"]),
            "elegiveis":     int(row["Elegíveis"]),
            "com_premio":    int(row["Com_Prêmio"]),
            "valor_total":   _fmt_moeda(float(row["Valor_Total_RV"])),
            "premio_medio":  _fmt_moeda(float(row["Prêmio_Médio"])),
            "salario_total": _fmt_moeda(float(row["Salário_Total_Folha"])),
        }
        for _, row in resumo.sort_values("Valor_Total_RV", ascending=False).iterrows()
    ]

    colunas = list(detalhado.columns)
    linhas = [
        [_formatar_celula(col, row[col]) for col in colunas]
        for _, row in detalhado.iterrows()
    ]

    return {
        "resumo_geral": resumo_geral,
        "resumo_grupo": resumo_grupo,
        "colunas": colunas,
        "linhas": linhas,
    }

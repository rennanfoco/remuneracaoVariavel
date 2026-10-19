from collections import defaultdict

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import services
from .forms import COMPETENCIA_RE, CompetenciaForm, EnviarArquivoForm, ExecutarCalculoForm
from .models import ArquivoCompetencia, ExecucaoCalculo


def _competencia_escolhida(request) -> str:
    """Competência escolhida em ?competencia=AAAA-MM; sem ela (ou inválida), a padrão."""
    form = CompetenciaForm(request.GET)
    return form.cleaned_data["competencia"] if form.is_valid() else services.competencia_padrao()


def _voltar_para(nome_da_url: str, competencia: str):
    return redirect(f"{reverse(nome_da_url)}?competencia={competencia}")


@login_required
def arquivos(request):
    """Aba Arquivos: o status atual dos arquivos de uma competência, com envio/substituição de cada um."""
    if request.method == "POST":
        form = EnviarArquivoForm(request.POST, request.FILES)
        competencia_postada = request.POST.get("competencia", "")
        competencia = competencia_postada if COMPETENCIA_RE.match(competencia_postada) else services.competencia_padrao()
        if not form.is_valid():
            messages.error(request, "Escolha o arquivo a enviar.")
            return _voltar_para("calculo:arquivos", competencia)

        tipo, arquivo = form.cleaned_data["tipo"], form.cleaned_data["arquivo"]
        rotulo = dict(ArquivoCompetencia._meta.get_field("tipo").choices)[tipo]
        validacao = services.validar_arquivo(tipo, arquivo, competencia)
        if validacao["ok"]:
            registro = services.registrar_arquivo(competencia, tipo, arquivo, request.user, validacao)
            messages.success(request, f"{rotulo}: arquivo recebido ({registro.resumo}).")
            for aviso in validacao["avisos"]:
                messages.warning(request, f"{rotulo}: {aviso}")
        else:
            for erro in validacao["erros"]:
                messages.error(request, f"{rotulo}: arquivo não aceito — {erro}")
        return _voltar_para("calculo:arquivos", competencia)

    competencia = _competencia_escolhida(request)
    situacao = services.situacao_da_competencia(competencia)
    versoes = defaultdict(list)
    for versao in ArquivoCompetencia.objects.filter(competencia=competencia).select_related("enviado_por"):
        versoes[versao.tipo].append(versao)
    linhas = [{"item": item, "anteriores": versoes[item.tipo][1:]} for item in situacao.itens]
    return render(request, "calculo/arquivos.html", {"competencia": competencia, "situacao": situacao, "linhas": linhas})


@login_required
def executar(request):
    """Aba Cálculo: calcula a competência com o status atual dos arquivos (não reenvia nada)."""
    if request.method == "POST":
        form = ExecutarCalculoForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Competência inválida — use AAAA-MM, ex: 2026-06.")
            return redirect("calculo:executar")

        competencia = form.cleaned_data["competencia"]
        try:
            execucao = services.iniciar_calculo(competencia, request.user, form.cleaned_data["buscar_totvs"])
        except services.CalculoBloqueado as bloqueio:
            for pendencia in bloqueio.pendencias:
                messages.error(request, pendencia)
        except services.ErroTotvs as erro:
            messages.error(request, str(erro))
        else:
            return redirect("calculo:resultado", pk=execucao.pk)
        return _voltar_para("calculo:executar", competencia)

    competencia = _competencia_escolhida(request)
    situacao = services.situacao_da_competencia(competencia)
    colaboradores = next(i for i in situacao.itens if i.tipo == "colaboradores")
    # pendências que o botão do TOTVS não resolve: sem elas, só a base de colaboradores pode faltar
    outras_pendencias = [i.pendencia for i in situacao.itens if i.pendencia and i.tipo != "colaboradores"]
    return render(request, "calculo/executar.html", {
        "competencia": competencia,
        "situacao": situacao,
        "colaboradores": colaboradores,
        "outras_pendencias": outras_pendencias,
        "form": ExecutarCalculoForm(initial={"competencia": competencia}),
    })


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
        with pd.ExcelFile(execucao.arquivo_relatorio.path) as xls:
            detalhado = xls.parse("Detalhado")
            resumo = xls.parse("Resumo por Grupo")
            # só existe quando alguém ficou de fora (cargo sem grupo de cálculo) — ver rv/output.py
            nao_calculados = xls.parse("Não calculados") if "Não calculados" in xls.sheet_names else None
    except Exception:
        return None

    processados = int(resumo["Total"].sum())
    elegiveis   = int(resumo["Elegíveis"].sum())
    com_premio  = int(resumo["Com_Prêmio"].sum())
    resumo_geral = {
        "processados":  processados,
        "elegiveis":    elegiveis,
        "com_premio":   com_premio,
        "sem_premio":   elegiveis - com_premio,
        "inelegiveis":  processados - elegiveis,
        "nao_calculados": 0 if nao_calculados is None else len(nao_calculados),
        "valor_total":  _fmt_moeda(float(resumo["Valor_Total_RV"].sum())),
    }

    sem_calculo = None
    if nao_calculados is not None and not nao_calculados.empty:
        colunas_nc = list(nao_calculados.columns)
        sem_calculo = {
            "total": len(nao_calculados),
            "por_cargo": [
                {"cargo": cargo, "quantidade": int(qtd)}
                for cargo, qtd in nao_calculados["Cargo"].value_counts().items()
            ],
            "colunas": colunas_nc,
            "linhas": [
                [_formatar_celula(col, row[col]) for col in colunas_nc]
                for _, row in nao_calculados.iterrows()
            ],
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
        "sem_calculo": sem_calculo,
        "colunas": colunas,
        "linhas": linhas,
    }

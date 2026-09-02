"""
Models de regras de negócio — equivalente estruturado do referencias.xlsx.

Espelha o que config.py já produz em memória (REGRAS[grupo][indicador] com
lista de faixas, CARGOS_GRUPO, TETOS, METAS_MENSAIS, parâmetros TOTVS), só
que como tabelas relacionais com integridade referencial garantida pelo
banco — em vez de checagens manuais em runtime.

Os nomes de indicador e as escolhas de modelo/direção usam os mesmos valores
(minúsculos) já usados em todo o resto do projeto (rv/engine.py, rv/loader.py,
rv/calculators/calculadora.py), para que os comandos importar_referencias /
exportar_referencias não precisem de nenhuma tradução.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

MODELO_CHOICES = [
    ("percentual", "% do Salário"),
    ("teto_fixo", "Teto Fixo (R$)"),
    # Sentinela usada por cargos que não recebem RV (ex: cargos administrativos
    # fora do programa). Nunca tem IndicadorRegra associado, e config.py (lado
    # legado) ignora esse valor ao ler a aba Grupos — mantém exatamente o
    # comportamento de hoje, onde "desconsiderar" só existe na aba Cargos.
    ("desconsiderar", "Desconsiderar (sem RV)"),
]

DIRECAO_CHOICES = [
    ("maior", "Maior é melhor"),
    ("menor", "Menor é melhor"),
]

INDICADOR_CHOICES = [
    ("dma", "DMA"),
    ("nps", "NPS"),
    ("faturamento", "Faturamento (% atingimento)"),
    ("nonrev", "NONREV"),
    ("preventiva", "Preventiva"),
    ("bate_patio", "Bate Pátio"),
]


class Grupo(models.Model):
    """
    Grupo de cálculo (atendente, lider_frota, mecanico, ...). Define se a
    base do prêmio é o salário do colaborador ou um teto fixo em R$.
    Equivalente à aba Grupos do referencias.xlsx.
    """
    nome = models.SlugField(max_length=50, unique=True, help_text="Minúsculo, sem espaços — ex: lider_frota")
    modelo = models.CharField(max_length=20, choices=MODELO_CHOICES)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Grupo"
        verbose_name_plural = "Grupos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Cargo(models.Model):
    """
    Mapeia o nome exato do cargo (como vem do TOTVS RM) ao grupo de cálculo.
    Equivalente à aba Cargos do referencias.xlsx. O teto só é usado quando
    grupo.modelo == "teto_fixo" (equivalente à aba Tetos).
    """
    nome = models.CharField(max_length=150, unique=True, help_text="Nome exato conforme retornado pelo TOTVS RM")
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name="cargos")
    teto = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Obrigatório se o grupo for de modelo 'Teto Fixo'",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.grupo_id and self.grupo.modelo == "teto_fixo" and self.teto is None:
            raise ValidationError({
                "teto": "Obrigatório: este cargo pertence a um grupo de modelo 'Teto Fixo'.",
            })


class IndicadorRegra(models.Model):
    """
    Um indicador (dma, nps, nonrev, ...) que conta para o cálculo de um
    grupo, com sua direção (maior/menor é melhor) e, opcionalmente, a chave
    usada para buscar os limites em MetaMensal (quando o limite varia mês a
    mês, ex: NPS e NONREV) em vez de vir fixo em FaixaCalculo.
    Equivalente a uma combinação (grupo, indicador) na aba Regras_Calculo.
    """
    grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE, related_name="indicadores")
    indicador = models.CharField(max_length=20, choices=INDICADOR_CHOICES)
    direcao = models.CharField(max_length=10, choices=DIRECAO_CHOICES, default="maior")
    chave_meta = models.CharField(
        max_length=50, blank=True,
        help_text="Se preenchido, os limites (min/max) vêm de Metas Mensais em vez das faixas abaixo",
    )
    depende_indicador = models.CharField(
        max_length=20, choices=INDICADOR_CHOICES, blank=True,
        help_text=(
            "Opcional: outro indicador do MESMO grupo do qual este depende — "
            "ex: 'dma' só conta se 'faturamento' bater o valor mínimo abaixo. "
            "Em branco = sem dependência (padrão)."
        ),
    )
    depende_valor_min = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Valor real mínimo (não faixa) que 'Depende indicador' precisa atingir",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Indicador de Regra"
        verbose_name_plural = "Indicadores de Regra"
        unique_together = ("grupo", "indicador")
        ordering = ["grupo__nome", "indicador"]

    def __str__(self):
        return f"{self.grupo.nome} / {self.get_indicador_display()}"


class FaixaCalculo(models.Model):
    """
    Uma faixa de atingimento para um indicador — número maior = melhor
    resultado. Quantidade de faixas por indicador é livre (1, 2, 3, ...).
    Ignorada em tempo de cálculo se o indicador tiver chave_meta preenchida
    (nesse caso os limites vêm de MetaMensal; o pct aqui ainda é usado).
    """
    indicador_regra = models.ForeignKey(IndicadorRegra, on_delete=models.CASCADE, related_name="faixas")
    faixa = models.PositiveSmallIntegerField(help_text="1, 2, 3... — maior número = melhor faixa")
    valor_min = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    valor_max = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    pct = models.DecimalField(max_digits=6, decimal_places=4, help_text="Ex: 0,15 = 15% do salário/teto")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Faixa de Cálculo"
        verbose_name_plural = "Faixas de Cálculo"
        unique_together = ("indicador_regra", "faixa")
        ordering = ["indicador_regra", "faixa"]

    def __str__(self):
        return f"{self.indicador_regra} — faixa {self.faixa}"


class MetaMensal(models.Model):
    """
    Meta mensal (NPS, NONREV) usada quando um IndicadorRegra tem chave_meta
    preenchida. Mesma estrutura de faixas de FaixaCalculo, mas por
    competência. Equivalente à aba Metas_Mensais do referencias.xlsx.
    """
    mes = models.CharField(max_length=7, help_text="AAAA-MM, ex: 2026-06")
    chave = models.CharField(max_length=50, help_text="Ex: nps_lider_frota, nonrev")
    faixa = models.PositiveSmallIntegerField()
    valor_min = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    valor_max = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Meta Mensal"
        verbose_name_plural = "Metas Mensais"
        unique_together = ("mes", "chave", "faixa")
        ordering = ["-mes", "chave", "faixa"]

    def __str__(self):
        return f"{self.mes} / {self.chave} — faixa {self.faixa}"


class Loja(models.Model):
    """
    Cadastro de qual regional cada loja pertence — fonte de verdade
    independente de quem está na folha do mês. Sem isso, uma loja sem
    NINGUÉM alocado no momento (reforma, troca de gestão etc.) desaparecia
    dos totais da regional sem aviso (ver motor_calculo/rv/engine.py).
    Equivalente à aba Lojas do referencias.xlsx.
    """
    unidade = models.CharField(max_length=20, unique=True, help_text="Código da loja no TOTVS, ex: SAO10")
    regional = models.CharField(max_length=50, help_text="Ex: NORDESTE, SUDESTE, SUL")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Loja"
        verbose_name_plural = "Lojas"
        ordering = ["regional", "unidade"]

    def __str__(self):
        return f"{self.unidade} ({self.regional})"


class MetaFaturamentoRegional(models.Model):
    """
    Meta de faturamento de cada Regional, em R$, digitada direto aqui — não
    é somada a partir das metas individuais dos atendentes das lojas.
    Equivalente à aba Metas_Faturamento_Regional do referencias.xlsx.
    """
    mes = models.CharField(max_length=7, help_text="AAAA-MM, ex: 2026-06")
    regional = models.CharField(max_length=50, help_text="Ex: NORDESTE, SUDESTE, SUL")
    meta = models.DecimalField(max_digits=12, decimal_places=2, help_text="Meta de faturamento em R$")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Meta de Faturamento Regional"
        verbose_name_plural = "Metas de Faturamento Regional"
        unique_together = ("mes", "regional")
        ordering = ["-mes", "regional"]

    def __str__(self):
        return f"{self.mes} / {self.regional}"


class ParametroTOTVS(models.Model):
    """
    Parâmetros técnicos de integração com o TOTVS RM (código do evento de
    RV, código da coligada, separador do TXT). Equivalente à aba TOTVS do
    referencias.xlsx.
    """
    parametro = models.CharField(max_length=50, unique=True)
    valor = models.CharField(max_length=200)
    descricao = models.CharField(max_length=255, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Parâmetro TOTVS"
        verbose_name_plural = "Parâmetros TOTVS"
        ordering = ["parametro"]

    def __str__(self):
        return f"{self.parametro} = {self.valor}"


# Todo model de regra de negócio cujas alterações por importação precisam
# poder ser desfeitas/refeitas em bloco — usado por apps/regras/services.py.
MODELOS_VERSIONADOS = [
    Grupo, Cargo, IndicadorRegra, FaixaCalculo,
    MetaMensal, MetaFaturamentoRegional, Loja, ParametroTOTVS,
]


class ImportacaoReferencias(models.Model):
    """
    Registro de uma importação de planilha para o banco — permite desfazer
    (reverter) ou refazer (reaplicar) TODAS as mudanças daquela importação
    de uma vez, em vez de registro por registro.

    Funciona marcando cada alteração feita durante a importação com o mesmo
    `identificador_lote` (usado como history_change_reason do
    django-simple-history em cada model de MODELOS_VERSIONADOS). Reverter
    restaura cada registro tocado ao estado imediatamente anterior a esta
    importação (ou apaga, se a importação tiver criado o registro). Reaplicar
    faz o caminho inverso — restaura o snapshot desta própria importação.

    Limitação conhecida: se um registro tocado por esta importação foi
    editado manualmente DEPOIS dela, reverter/reaplicar desfaz essa edição
    manual também (não há resolução de conflito — é uma restauração em
    bloco, como um "voltar no tempo" pra aquele conjunto de registros).
    """
    STATUS_CHOICES = [("aplicada", "Aplicada"), ("revertida", "Revertida")]

    arquivo_nome = models.CharField(max_length=255)
    importado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="importacoes_feitas",
    )
    importado_em = models.DateTimeField(auto_now_add=True)
    identificador_lote = models.CharField(max_length=40, unique=True)
    resumo = models.TextField(blank=True, help_text="Ex: 9 grupos, 48 cargos, 24 indicadores...")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="aplicada")

    alterado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", help_text="Quem reverteu ou reaplicou por último",
    )
    alterado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Importação de Referências"
        verbose_name_plural = "Importações de Referências"
        ordering = ["-importado_em"]

    def __str__(self):
        return f"{self.arquivo_nome} — {self.importado_em:%d/%m/%Y %H:%M} ({self.get_status_display()})"

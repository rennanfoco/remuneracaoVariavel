"""
Models do cálculo de RV — dão ao portal um histórico auditável que a CLI nunca teve (quem rodou o
quê, quando, com quais arquivos).

Os arquivos de entrada pertencem a uma COMPETÊNCIA (ArquivoCompetencia, aba Arquivos) e o cálculo
(ExecucaoCalculo, aba Cálculo) usa o "status atual" dela: a versão mais recente de cada tipo.
Cada execução guarda exatamente quais versões usou, então dá para reproduzir um cálculo mesmo que
um arquivo seja substituído depois.
"""

from django.conf import settings
from django.db import models

# Espelha rv.loader.PADROES — rótulos amigáveis para a tela de upload.
TIPO_ARQUIVO_CHOICES = [
    ("colaboradores", "Colaboradores (TOTVS RM)"),
    ("coral", "Coral — faturamento/DMA (dma-pro-rata)"),
    ("nps", "NPS por loja (Power BI)"),
    ("preventiva", "Preventivas (Frotas)"),
    ("bate_patio", "Fechamento / Bate Pátio (Frotas)"),
    ("nonrev", "NONREV (Frotas)"),
    ("meta_faturamento", "Metas de faturamento (Base metas .xlsx ou Importação Planilha .csv)"),
    ("mapeamento", "Lista de Logins (login → matrícula)"),
]

# Sem estes o cálculo não roda. NONREV é opcional (grupos que dependem dele recebem 0).
# "colaboradores" é obrigatório mas tem regra própria: vem do TOTVS ou de um CSV, sempre da competência.
TIPOS_OBRIGATORIOS = {
    "colaboradores", "coral", "nps", "preventiva", "bate_patio", "meta_faturamento", "mapeamento",
}

# Muda pouco de mês a mês (login -> matrícula): se a competência não tem uma, vale a mais recente das anteriores.
TIPOS_HERDADOS_DA_COMPETENCIA_ANTERIOR = {"mapeamento"}

STATUS_CHOICES = [
    ("processando", "Processando"),
    ("concluido", "Concluído"),
    ("erro", "Erro"),
]


class ExecucaoCalculo(models.Model):
    competencia = models.CharField(max_length=7, help_text="AAAA-MM")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="processando")
    usar_api_totvs = models.BooleanField(
        default=False, help_text="Se marcado, os colaboradores foram buscados no TOTVS RM nesta execução",
    )
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="execucoes")
    iniciado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    log = models.TextField(blank=True)
    erro_mensagem = models.TextField(blank=True)

    arquivos_usados = models.ManyToManyField(
        "ArquivoCompetencia", blank=True, related_name="execucoes",
        help_text="As versões exatas dos arquivos que este cálculo usou",
    )

    arquivo_txt = models.FileField(upload_to="execucoes/%Y/%m/", null=True, blank=True)
    arquivo_relatorio = models.FileField(upload_to="execucoes/%Y/%m/", null=True, blank=True)

    class Meta:
        verbose_name = "Execução de Cálculo"
        verbose_name_plural = "Execuções de Cálculo"
        ordering = ["-iniciado_em"]

    def __str__(self):
        return f"RV {self.competencia} — {self.get_status_display()} ({self.iniciado_em:%d/%m/%Y %H:%M})"


class ArquivoUpload(models.Model):
    """Legado: arquivos enviados junto com o cálculo, antes da aba Arquivos. Só para exibir execuções antigas."""
    execucao = models.ForeignKey(ExecucaoCalculo, on_delete=models.CASCADE, related_name="arquivos")
    tipo = models.CharField(max_length=30, choices=TIPO_ARQUIVO_CHOICES)
    arquivo = models.FileField(upload_to="uploads/%Y/%m/")

    class Meta:
        verbose_name = "Arquivo Enviado"
        verbose_name_plural = "Arquivos Enviados"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.arquivo.name}"


class ArquivoCompetencia(models.Model):
    """
    Um arquivo de entrada de uma competência. Substituir um arquivo cria uma nova linha — a mais
    recente de cada (competência, tipo) é a versão atual, e as anteriores ficam guardadas.
    """
    ORIGEM_CHOICES = [("upload", "Enviado"), ("totvs", "Buscado no TOTVS")]

    competencia = models.CharField(max_length=7, help_text="AAAA-MM", db_index=True)
    tipo = models.CharField(max_length=30, choices=TIPO_ARQUIVO_CHOICES)
    arquivo = models.FileField(upload_to="arquivos/%Y/%m/")
    nome_original = models.CharField(max_length=255)
    origem = models.CharField(max_length=10, choices=ORIGEM_CHOICES, default="upload")
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="arquivos_enviados")
    enviado_em = models.DateTimeField(auto_now_add=True)
    resumo = models.CharField(max_length=255, blank=True, help_text="Ex: 324 logins, R$ 6.589.409,75 faturados")
    avisos = models.TextField(blank=True, help_text="Um aviso por linha, da validação feita no envio")

    class Meta:
        verbose_name = "Arquivo da Competência"
        verbose_name_plural = "Arquivos das Competências"
        ordering = ["-enviado_em", "-id"]

    def __str__(self):
        return f"{self.competencia} · {self.get_tipo_display()} · {self.nome_original}"

    @property
    def lista_de_avisos(self) -> list[str]:
        return [a for a in self.avisos.splitlines() if a.strip()]

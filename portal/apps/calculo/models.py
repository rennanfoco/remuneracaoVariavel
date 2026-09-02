"""
Models de execução do cálculo de RV — dão ao portal um histórico auditável
que a CLI nunca teve (quem rodou o quê, quando, com quais arquivos).
"""

from django.conf import settings
from django.db import models

# Espelha rv.loader.PADROES — rótulos amigáveis para a tela de upload.
TIPO_ARQUIVO_CHOICES = [
    ("colaboradores", "Colaboradores (TOTVS RM)"),
    ("coral", "Coral — faturamento/DMA (dma-accumulated)"),
    ("nps", "NPS por loja (Power BI)"),
    ("preventiva", "Preventivas (Frotas)"),
    ("bate_patio", "Fechamento / Bate Pátio (Frotas)"),
    ("nonrev", "NONREV (Frotas)"),
    ("meta_faturamento", "Meta de Faturamento (Importação Planilha)"),
    ("mapeamento", "Lista de Logins (login → matrícula)"),
]

STATUS_CHOICES = [
    ("processando", "Processando"),
    ("concluido", "Concluído"),
    ("erro", "Erro"),
]


class ExecucaoCalculo(models.Model):
    competencia = models.CharField(max_length=7, help_text="AAAA-MM")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="processando")
    usar_api_totvs = models.BooleanField(
        default=False, help_text="Se marcado, colaboradores vêm da API do TOTVS RM em vez de upload",
    )
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="execucoes")
    iniciado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    log = models.TextField(blank=True)
    erro_mensagem = models.TextField(blank=True)

    arquivo_txt = models.FileField(upload_to="execucoes/%Y/%m/", null=True, blank=True)
    arquivo_relatorio = models.FileField(upload_to="execucoes/%Y/%m/", null=True, blank=True)

    class Meta:
        verbose_name = "Execução de Cálculo"
        verbose_name_plural = "Execuções de Cálculo"
        ordering = ["-iniciado_em"]

    def __str__(self):
        return f"RV {self.competencia} — {self.get_status_display()} ({self.iniciado_em:%d/%m/%Y %H:%M})"


class ArquivoUpload(models.Model):
    execucao = models.ForeignKey(ExecucaoCalculo, on_delete=models.CASCADE, related_name="arquivos")
    tipo = models.CharField(max_length=30, choices=TIPO_ARQUIVO_CHOICES)
    arquivo = models.FileField(upload_to="uploads/%Y/%m/")

    class Meta:
        verbose_name = "Arquivo Enviado"
        verbose_name_plural = "Arquivos Enviados"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.arquivo.name}"

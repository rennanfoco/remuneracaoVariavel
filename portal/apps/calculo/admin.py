from django.contrib import admin

from .models import ArquivoUpload, ExecucaoCalculo


class ArquivoUploadInline(admin.TabularInline):
    model = ArquivoUpload
    extra = 0
    can_delete = False
    readonly_fields = ("tipo", "arquivo")


@admin.register(ExecucaoCalculo)
class ExecucaoCalculoAdmin(admin.ModelAdmin):
    list_display = ("competencia", "status", "iniciado_por", "iniciado_em")
    list_filter = ("status", "competencia")
    readonly_fields = (
        "competencia", "status", "usar_api_totvs", "iniciado_por", "iniciado_em",
        "concluido_em", "log", "erro_mensagem", "arquivo_txt", "arquivo_relatorio",
    )
    inlines = [ArquivoUploadInline]

    def has_add_permission(self, request):
        return False  # execuções só são criadas pelo fluxo normal (apps/calculo/views.py)

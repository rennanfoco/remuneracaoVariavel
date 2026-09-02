from django.contrib import admin

from .models import (
    Cargo, FaixaCalculo, Grupo, IndicadorRegra, Loja, MetaFaturamentoRegional,
    MetaMensal, ParametroTOTVS,
)


@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    list_display = ("nome", "modelo")
    list_filter = ("modelo",)
    search_fields = ("nome",)


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nome", "grupo", "teto")
    list_filter = ("grupo",)
    search_fields = ("nome",)
    autocomplete_fields = ("grupo",)


class FaixaCalculoInline(admin.TabularInline):
    model = FaixaCalculo
    extra = 1
    ordering = ("faixa",)


@admin.register(IndicadorRegra)
class IndicadorRegraAdmin(admin.ModelAdmin):
    list_display = ("grupo", "indicador", "loja", "direcao", "chave_meta", "depende_indicador", "depende_valor_min")
    list_filter = ("indicador", "direcao", "grupo", "depende_indicador", "loja")
    autocomplete_fields = ("grupo", "loja")
    inlines = [FaixaCalculoInline]


@admin.register(MetaMensal)
class MetaMensalAdmin(admin.ModelAdmin):
    list_display = ("mes", "chave", "faixa", "valor_min", "valor_max")
    list_filter = ("mes", "chave")
    ordering = ("-mes", "chave", "faixa")
    actions = ["duplicar_para_proximo_mes"]

    @admin.action(description="Duplicar linhas selecionadas para o próximo mês")
    def duplicar_para_proximo_mes(self, request, queryset):
        """
        Copia as linhas selecionadas incrementando o mês em 1 — a operação
        manual mais comum hoje (RH duplica o bloco do mês anterior e ajusta
        os valores). Se o mês seguinte já tiver a mesma (chave, faixa),
        pula essa linha em vez de sobrescrever ou duplicar.
        """
        criadas = 0
        ignoradas = 0
        for meta in queryset:
            ano, mes = map(int, meta.mes.split("-"))
            mes += 1
            if mes > 12:
                mes, ano = 1, ano + 1
            proximo_mes = f"{ano:04d}-{mes:02d}"

            if MetaMensal.objects.filter(mes=proximo_mes, chave=meta.chave, faixa=meta.faixa).exists():
                ignoradas += 1
                continue

            MetaMensal.objects.create(
                mes=proximo_mes, chave=meta.chave, faixa=meta.faixa,
                valor_min=meta.valor_min, valor_max=meta.valor_max,
            )
            criadas += 1

        self.message_user(request, f"{criadas} linha(s) criada(s), {ignoradas} já existiam e foram ignoradas.")


@admin.register(Loja)
class LojaAdmin(admin.ModelAdmin):
    list_display = ("unidade", "regional")
    list_filter = ("regional",)
    search_fields = ("unidade",)
    ordering = ("regional", "unidade")


@admin.register(MetaFaturamentoRegional)
class MetaFaturamentoRegionalAdmin(admin.ModelAdmin):
    list_display = ("mes", "regional", "meta")
    list_filter = ("mes", "regional")
    ordering = ("-mes", "regional")
    actions = ["duplicar_para_proximo_mes"]

    @admin.action(description="Duplicar linhas selecionadas para o próximo mês")
    def duplicar_para_proximo_mes(self, request, queryset):
        """Mesma lógica de MetaMensalAdmin — duplica pro mês seguinte, pula se já existir."""
        criadas = 0
        ignoradas = 0
        for meta in queryset:
            ano, mes = map(int, meta.mes.split("-"))
            mes += 1
            if mes > 12:
                mes, ano = 1, ano + 1
            proximo_mes = f"{ano:04d}-{mes:02d}"

            if MetaFaturamentoRegional.objects.filter(mes=proximo_mes, regional=meta.regional).exists():
                ignoradas += 1
                continue

            MetaFaturamentoRegional.objects.create(
                mes=proximo_mes, regional=meta.regional, meta=meta.meta,
            )
            criadas += 1

        self.message_user(request, f"{criadas} linha(s) criada(s), {ignoradas} já existiam e foram ignoradas.")


@admin.register(ParametroTOTVS)
class ParametroTOTVSAdmin(admin.ModelAdmin):
    list_display = ("parametro", "valor", "descricao")

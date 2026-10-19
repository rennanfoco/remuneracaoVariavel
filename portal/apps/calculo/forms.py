import re

from django import forms

from .models import TIPO_ARQUIVO_CHOICES

COMPETENCIA_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validar_competencia(valor: str) -> str:
    valor = valor.strip()
    if not COMPETENCIA_RE.match(valor):
        raise forms.ValidationError("Formato inválido — use AAAA-MM, ex: 2026-06.")
    return valor


class CompetenciaForm(forms.Form):
    """Escolha da competência (GET) nas abas Arquivos e Cálculo."""
    competencia = forms.CharField(label="Competência", max_length=7)

    def clean_competencia(self):
        return _validar_competencia(self.cleaned_data["competencia"])


class EnviarArquivoForm(forms.Form):
    competencia = forms.CharField(max_length=7, widget=forms.HiddenInput)
    tipo = forms.ChoiceField(choices=TIPO_ARQUIVO_CHOICES, widget=forms.HiddenInput)
    arquivo = forms.FileField(label="Arquivo")

    def clean_competencia(self):
        return _validar_competencia(self.cleaned_data["competencia"])


class ExecutarCalculoForm(forms.Form):
    competencia = forms.CharField(max_length=7, widget=forms.HiddenInput)
    buscar_totvs = forms.BooleanField(
        label="Buscar colaboradores no TOTVS agora",
        required=False,
    )

    def clean_competencia(self):
        return _validar_competencia(self.cleaned_data["competencia"])

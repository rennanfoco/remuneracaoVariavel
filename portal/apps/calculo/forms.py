import re

from django import forms

COMPETENCIA_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Mesma ordem/rótulos de rv.loader — ajuda quem não tem domínio técnico a
# saber exatamente qual arquivo vai em qual campo.
CAMPOS_ARQUIVO = [
    ("colaboradores", "Colaboradores (TOTVS RM)", False),
    ("coral", "Coral — faturamento/DMA (dma-accumulated)", True),
    ("nps", "NPS por loja (Power BI)", True),
    ("preventiva", "Preventivas (Frotas)", True),
    ("bate_patio", "Fechamento / Bate Pátio (Frotas)", True),
    ("nonrev", "NONREV (Frotas) — opcional", False),
    ("meta_faturamento", "Meta de Faturamento (Importação Planilha)", True),
    ("mapeamento", "Lista de Logins (login → matrícula)", True),
]


class ExecutarCalculoForm(forms.Form):
    competencia = forms.CharField(
        label="Competência",
        max_length=7,
        widget=forms.TextInput(attrs={"placeholder": "AAAA-MM, ex: 2026-06"}),
    )
    usar_api_totvs = forms.BooleanField(
        label="Buscar colaboradores direto da API do TOTVS RM (em vez de enviar arquivo)",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for tipo, rotulo, obrigatorio in CAMPOS_ARQUIVO:
            self.fields[tipo] = forms.FileField(
                label=rotulo,
                required=obrigatorio,
                widget=forms.ClearableFileInput(attrs={"class": "input-file"}),
            )

    def clean_competencia(self):
        valor = self.cleaned_data["competencia"].strip()
        if not COMPETENCIA_RE.match(valor):
            raise forms.ValidationError("Formato inválido — use AAAA-MM, ex: 2026-06.")
        return valor

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("usar_api_totvs") and not cleaned.get("colaboradores"):
            self.add_error(
                "colaboradores",
                "Envie o arquivo de colaboradores, ou marque a opção de buscar via API do TOTVS RM.",
            )
        return cleaned

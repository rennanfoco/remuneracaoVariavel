"""
Importa o referencias.xlsx atual para o banco (app regras) — migração
one-time. Reaproveita literalmente os parsers de config.py (_parse_grupos_modelo,
_parse_cargos, _parse_tetos, _parse_regras, _parse_metas, _parse_totvs) — a
mesma lógica que main.py já usa hoje — então o resultado é garantidamente
equivalente ao que a CLI calcula com o mesmo arquivo.

Idempotente: usa update_or_create por chave natural (nome do grupo/cargo,
combinação grupo+indicador, mes+chave+faixa) — pode ser rodado de novo sem
duplicar nada.

Nota: importar o módulo config executa a validação própria dele
(_grupos_sem_modelo) contra o referencias.xlsx PADRÃO do projeto (não
necessariamente o --arquivo passado aqui) — na prática isso não importa
porque os dois são o mesmo arquivo no uso normal deste comando.

Uso:
  python manage.py importar_referencias --arquivo referencias.xlsx
"""

import uuid
from decimal import Decimal
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from simple_history.utils import update_change_reason

import config as config_legado
from apps.regras.models import (
    Cargo, FaixaCalculo, Grupo, IndicadorRegra, Loja, MetaFaturamentoRegional,
    MetaMensal, ParametroTOTVS,
)


def _dec(valor):
    return None if valor is None else Decimal(str(valor))


class Command(BaseCommand):
    help = (
        "Importa referencias.xlsx (Grupos, Cargos, Regras_Calculo, Tetos, Metas_Mensais, "
        "Metas_Faturamento_Regional, Lojas, TOTVS) para o banco."
    )

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", default="referencias.xlsx", help="Caminho do referencias.xlsx a importar")
        parser.add_argument(
            "--lote", default=None,
            help=(
                "Identificador do lote de importação, usado para marcar cada alteração "
                "(history_change_reason) e permitir reverter/reaplicar esta importação "
                "inteira de uma vez depois (ver apps/regras/services.py). Gerado "
                "automaticamente se não informado."
            ),
        )

    def handle(self, *args, **options):
        caminho = Path(options["arquivo"])
        if not caminho.exists():
            raise CommandError(f"Arquivo não encontrado: {caminho}")
        self.lote = options.get("lote") or uuid.uuid4().hex

        # Fecha o arquivo explicitamente assim que os dados são extraídos —
        # sem isso, o handle fica aberto (sobretudo no Windows) e quem chamou
        # este comando com um arquivo em diretório temporário não consegue
        # limpar esse diretório depois (PermissionError).
        with pd.ExcelFile(caminho) as xls:
            grupos_modelo = config_legado._parse_grupos_modelo(xls)
            cargos_grupo = config_legado._parse_cargos(xls)
            tetos = config_legado._parse_tetos(xls)
            regras = config_legado._parse_regras(xls)
            metas = config_legado._parse_metas(xls)
            metas_fat_reg = config_legado._parse_metas_faturamento_regional(xls)
            lojas = config_legado._parse_lojas(xls)
            totvs = config_legado._parse_totvs(xls)

        with transaction.atomic():
            n_grupos = self._importar_grupos(grupos_modelo)
            n_cargos = self._importar_cargos(cargos_grupo, tetos)
            n_ind, n_faixas = self._importar_regras(regras)
            n_metas = self._importar_metas(metas)
            n_metas_fat_reg = self._importar_metas_faturamento_regional(metas_fat_reg)
            n_lojas = self._importar_lojas(lojas)
            n_totvs = self._importar_totvs(totvs)

        self.resumo = (
            f"{n_grupos} grupos, {n_cargos} cargos, {n_ind} indicadores ({n_faixas} faixas), "
            f"{n_metas} metas mensais, {n_metas_fat_reg} metas de faturamento regional, "
            f"{n_lojas} lojas, {n_totvs} parâmetros TOTVS"
        )
        self.stdout.write(self.style.SUCCESS(f"Importado de {caminho} (lote {self.lote}): {self.resumo}."))
        return self.resumo

    def _marcar(self, obj):
        """Marca a alteração com o identificador do lote desta importação —
        é isso que permite reverter/reaplicar a importação inteira depois."""
        update_change_reason(obj, self.lote)

    def _importar_grupos(self, grupos_modelo):
        n = 0
        for nome, modelo in grupos_modelo.items():
            obj, _criado = Grupo.objects.update_or_create(nome=nome, defaults={"modelo": modelo})
            self._marcar(obj)
            n += 1
        return n

    def _importar_cargos(self, cargos_grupo, tetos):
        n = 0
        grupos_cache = {g.nome: g for g in Grupo.objects.all()}
        for cargo_nome, grupo_nome in cargos_grupo.items():
            grupo = grupos_cache.get(grupo_nome)

            if grupo is None and grupo_nome == "desconsiderar":
                # Sentinela conhecida: cargo sem RV. Nunca esteve na aba
                # Grupos do xlsx original (não tem regras nem modelo de
                # cálculo) — cria aqui para não perder o mapeamento do
                # cargo ao exportar de volta.
                grupo, criado = Grupo.objects.get_or_create(
                    nome="desconsiderar", defaults={"modelo": "desconsiderar"},
                )
                grupos_cache[grupo.nome] = grupo
                if criado:
                    self._marcar(grupo)

            if grupo is None:
                self.stderr.write(self.style.WARNING(
                    f"Cargo '{cargo_nome}' referencia grupo '{grupo_nome}' "
                    f"inexistente na aba Grupos — pulando (verifique se é uma "
                    f"linha de instrução do template ou um grupo real faltando)."
                ))
                continue

            obj, _criado = Cargo.objects.update_or_create(
                nome=cargo_nome,
                defaults={"grupo": grupo, "teto": _dec(tetos.get(cargo_nome))},
            )
            self._marcar(obj)
            n += 1
        return n

    def _importar_regras(self, regras):
        n_ind = n_faixas = 0
        grupos_cache = {g.nome: g for g in Grupo.objects.all()}
        for grupo_nome, indicadores in regras.items():
            grupo = grupos_cache.get(grupo_nome)
            if grupo is None:
                self.stderr.write(self.style.WARNING(
                    f"Regras_Calculo referencia grupo '{grupo_nome}' "
                    f"inexistente na aba Grupos — pulando."
                ))
                continue
            for indicador_nome, dados in indicadores.items():
                indicador_regra, _criado = IndicadorRegra.objects.update_or_create(
                    grupo=grupo, indicador=indicador_nome,
                    defaults={
                        "direcao": dados.get("direcao", "maior"),
                        "chave_meta": dados.get("chave_meta") or "",
                        "depende_indicador": dados.get("depende_indicador") or "",
                        "depende_valor_min": _dec(dados.get("depende_valor_min")),
                    },
                )
                self._marcar(indicador_regra)
                n_ind += 1
                for faixa in dados["faixas"]:
                    obj, _criado = FaixaCalculo.objects.update_or_create(
                        indicador_regra=indicador_regra, faixa=faixa["faixa"],
                        defaults={
                            "valor_min": _dec(faixa["min"]),
                            "valor_max": _dec(faixa["max"]),
                            "pct": _dec(faixa["pct"]),
                        },
                    )
                    self._marcar(obj)
                    n_faixas += 1
        return n_ind, n_faixas

    def _importar_metas(self, metas):
        n = 0
        for mes, chaves in metas.items():
            for chave, faixas in chaves.items():
                for faixa in faixas:
                    obj, _criado = MetaMensal.objects.update_or_create(
                        mes=mes, chave=chave, faixa=faixa["faixa"],
                        defaults={"valor_min": _dec(faixa["min"]), "valor_max": _dec(faixa["max"])},
                    )
                    self._marcar(obj)
                    n += 1
        return n

    def _importar_metas_faturamento_regional(self, metas_fat_reg):
        n = 0
        for mes, regionais in metas_fat_reg.items():
            for regional, meta in regionais.items():
                obj, _criado = MetaFaturamentoRegional.objects.update_or_create(
                    mes=mes, regional=regional, defaults={"meta": _dec(meta)},
                )
                self._marcar(obj)
                n += 1
        return n

    def _importar_lojas(self, lojas):
        n = 0
        for unidade, regional in lojas.items():
            obj, _criado = Loja.objects.update_or_create(unidade=unidade, defaults={"regional": regional})
            self._marcar(obj)
            n += 1
        return n

    def _importar_totvs(self, totvs):
        n = 0
        for parametro, valor in totvs.items():
            obj, _criado = ParametroTOTVS.objects.update_or_create(parametro=parametro, defaults={"valor": valor})
            self._marcar(obj)
            n += 1
        return n

#!/usr/bin/env python3
"""Vendas de um vendedor agrupadas por GRUPO de categoria.

Grupos (a partir do categorizar() do gerar_relatorio.py):
    Cosmeticos = Produtos A + B + C + D
    Acessorios = Acessorios A + B
    Maquinario = Maquinario
    Moveis     = Movelaria
    Outros     = Outros

Valores em base BRUTA por item (preco_unit * qtd) — mesma base dos rankings
de marca/produto do dashboard. O total liquido da venda (que bate com o
"Aprovados" da CA) e mostrado a parte, pra referencia.

Uso:
    python3 vendas_por_categoria.py "Jalena" [meses=12]

Saida: relatorio legivel + bloco JSON entre ===JSON=== / ===FIM===
"""
import calendar
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from ca_client import ContaAzulClient
from gerar_relatorio import categorizar, marca as marca_lista

MANAUS_TZ = timezone(timedelta(hours=-4))

ALIASES = {
    'Erivan Lima':            ['Erivan Lima'],
    'Róger Silva':            ['Róger Silva', 'Roger de Lima silva'],
    'Lucas de Mello Valente': ['Lucas de Mello Valente'],
    'Jalena':                 ['Jalena'],
    'Célio Alex':             ['Célio Alex'],
}

GRUPO = {
    'Produtos A': 'Cosmeticos', 'Produtos B': 'Cosmeticos',
    'Produtos C': 'Cosmeticos', 'Produtos D': 'Cosmeticos',
    'Acessorios A': 'Acessorios', 'Acessorios B': 'Acessorios',
    'Maquinario': 'Maquinario',
    'Movelaria': 'Moveis',
    'Outros': 'Outros',
}


def main():
    nome_alvo = sys.argv[1] if len(sys.argv) > 1 else 'Jalena'
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 12

    nomes_ca = ALIASES.get(nome_alvo, [nome_alvo])
    client = ContaAzulClient()
    vendedores = client.get('/venda/vendedores')
    ids = [v['id'] for v in vendedores if v['nome'] in nomes_ca]
    if not ids:
        print(f'ERRO: vendedor "{nome_alvo}" nao encontrado.')
        for v in vendedores:
            print(f'  - {v.get("nome")}')
        sys.exit(1)

    hoje = datetime.now(MANAUS_TZ).replace(tzinfo=None)
    janela = []
    a, m = hoje.year, hoje.month
    for _ in range(meses):
        janela.append((a, m))
        m -= 1
        if m < 1:
            m, a = 12, a - 1
    janela.reverse()

    print(f'Vendedor: {nome_alvo} ({len(ids)} cadastro(s)) | {len(janela)} mes(es)\n')

    por_grupo = defaultdict(float)
    por_grupo_mes = defaultdict(lambda: defaultdict(float))
    top_por_grupo = defaultdict(lambda: defaultdict(float))
    liquido_total = 0.0
    n_vendas = 0

    for ano_b, mes_b in janela:
        primeiro = f'{ano_b:04d}-{mes_b:02d}-01'
        ultimo = f'{ano_b:04d}-{mes_b:02d}-{calendar.monthrange(ano_b, mes_b)[1]:02d}'
        ym = f'{ano_b:04d}-{mes_b:02d}'
        mes_bruto = 0.0
        pagina = 1
        while True:
            res = client.get('/venda/busca', ids_vendedores=ids,
                             data_inicio=primeiro, data_fim=ultimo,
                             totais='APPROVED', pagina=pagina, tamanho_pagina=500)
            vendas = res.get('itens', []) if isinstance(res, dict) else []
            if not vendas:
                break
            for v in vendas:
                n_vendas += 1
                liquido_total += v.get('total', 0) or 0
                try:
                    itens_res = client.get(f"/venda/{v['id']}/itens", tamanho_pagina=200)
                    itens = itens_res.get('itens', []) if isinstance(itens_res, dict) else []
                except Exception as e:
                    print(f'    aviso: itens da venda {v.get("numero")} falharam: {e}')
                    continue
                for it in itens:
                    prod = it.get('nome', '')
                    val = (it.get('valor', 0) or 0) * (it.get('quantidade', 0) or 0)
                    g = GRUPO.get(categorizar(prod), 'Outros')
                    por_grupo[g] += val
                    por_grupo_mes[ym][g] += val
                    top_por_grupo[g][marca_lista(prod)] += val
                    mes_bruto += val
            if len(vendas) < 500:
                break
            pagina += 1
        print(f'  {ym}: R$ {mes_bruto:>10,.2f}')

    total = sum(por_grupo.values())
    print(f'\n{n_vendas} venda(s) | liquido (CA): R$ {liquido_total:,.2f} | bruto por item: R$ {total:,.2f}\n')
    print(f'{"Grupo":<14} {"Valor":>14} {"%":>7}')
    print('-' * 38)
    for g, v in sorted(por_grupo.items(), key=lambda kv: -kv[1]):
        print(f'{g:<14} R$ {v:>11,.2f} {v/max(total,1)*100:>6.1f}%')
    print('-' * 38)
    print(f'{"TOTAL":<14} R$ {total:>11,.2f}')

    for g in ('Cosmeticos', 'Acessorios', 'Moveis'):
        marcas = sorted(top_por_grupo[g].items(), key=lambda kv: -kv[1])[:5]
        if marcas:
            print(f'\nTop marcas — {g}:')
            for mk, mv in marcas:
                print(f'  {mk:<20} R$ {mv:>10,.2f}')

    print('\n===JSON===')
    print(json.dumps({
        'vendedor': nome_alvo,
        'gerado_em': hoje.strftime('%d/%m/%Y'),
        'meses': [f'{a:04d}-{m:02d}' for a, m in janela],
        'n_vendas': n_vendas,
        'liquido_total': round(liquido_total, 2),
        'bruto_total': round(total, 2),
        'por_grupo': {g: round(v, 2) for g, v in por_grupo.items()},
        'por_grupo_mes': {ym: {g: round(v, 2) for g, v in d.items()}
                          for ym, d in por_grupo_mes.items()},
        'top_marcas': {g: [[mk, round(mv, 2)] for mk, mv in
                           sorted(d.items(), key=lambda kv: -kv[1])[:5]]
                       for g, d in top_por_grupo.items()},
    }, ensure_ascii=False))
    print('===FIM===')


if __name__ == '__main__':
    main()

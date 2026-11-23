#!/usr/bin/env python3
"""Lista TODAS as vendas de um vendedor, venda a venda, agrupadas por mes.

Usa o total LIQUIDO de cada venda (o que bate com "Aprovados" na Conta Azul).

Uso:
    python3 vendas_vendedor.py "Jalena" [meses=24]

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

MANAUS_TZ = timezone(timedelta(hours=-4))
ALIASES = {
    'Erivan Lima':            ['Erivan Lima'],
    'Róger Silva':            ['Róger Silva', 'Roger de Lima silva'],
    'Lucas de Mello Valente': ['Lucas de Mello Valente'],
    'Jalena':                 ['Jalena'],
    'Célio Alex':             ['Célio Alex'],
}


def main():
    nome = sys.argv[1] if len(sys.argv) > 1 else 'Jalena'
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 24

    nomes_ca = ALIASES.get(nome, [nome])
    client = ContaAzulClient()
    vends = client.get('/venda/vendedores')
    ids = [v['id'] for v in vends if v['nome'] in nomes_ca]
    if not ids:
        print(f'ERRO: vendedor "{nome}" nao encontrado. Disponiveis:')
        for v in vends:
            print('  -', v.get('nome'))
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

    print(f'Vendedor: {nome} | janela de {meses} meses\n')
    por_mes = defaultdict(list)
    for ano_b, mes_b in janela:
        ym = f'{ano_b:04d}-{mes_b:02d}'
        primeiro = f'{ym}-01'
        ultimo = f'{ym}-{calendar.monthrange(ano_b, mes_b)[1]:02d}'
        for vid in ids:
            pagina = 1
            while True:
                res = client.get('/venda/busca', ids_vendedores=[vid],
                                 data_inicio=primeiro, data_fim=ultimo,
                                 totais='APPROVED', pagina=pagina, tamanho_pagina=500)
                vendas = res.get('itens', []) if isinstance(res, dict) else []
                if not vendas:
                    break
                for v in vendas:
                    try:
                        dt = datetime.strptime(v['data'], '%Y-%m-%d')
                    except (KeyError, ValueError):
                        continue
                    por_mes[ym].append({
                        'data': dt.strftime('%d/%m/%Y'),
                        'ord': dt.strftime('%Y-%m-%d'),
                        'numero': str(v.get('numero') or ''),
                        'cliente': ((v.get('cliente') or {}).get('nome') or '?').strip(),
                        'valor': round(v.get('total', 0) or 0, 2),
                    })
                if len(vendas) < 500:
                    break
                pagina += 1
        if por_mes[ym]:
            por_mes[ym].sort(key=lambda x: (x['ord'], x['numero']))
            tot = sum(x['valor'] for x in por_mes[ym])
            print(f'  {ym}: {len(por_mes[ym]):>3} venda(s) | R$ {tot:>10,.2f}')

    total = sum(x['valor'] for L in por_mes.values() for x in L)
    n = sum(len(L) for L in por_mes.values())
    print(f'\nTOTAL: {n} venda(s) | R$ {total:,.2f}')

    print('\n===JSON===')
    print(json.dumps({'vendedor': nome, 'gerado_em': hoje.strftime('%d/%m/%Y'),
                      'total': round(total, 2), 'n_vendas': n,
                      'por_mes': {k: v for k, v in sorted(por_mes.items()) if v}},
                     ensure_ascii=False))
    print('===FIM===')


if __name__ == '__main__':
    main()

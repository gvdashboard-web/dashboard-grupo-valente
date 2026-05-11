#!/usr/bin/env python3
"""Puxa o histórico de vendas de um vendedor por mês via API Conta Azul.

Uso:
    python3 puxar_historico_vendedor.py "Erivan Lima"
    python3 puxar_historico_vendedor.py "Erivan Lima" 12   # ultimos 12 meses
    python3 puxar_historico_vendedor.py "Erivan Lima" 24   # ultimos 24 meses
"""
import calendar
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from ca_client import ContaAzulClient


def fmt_brl(v):
    s = f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {s}'


def main():
    if len(sys.argv) < 2:
        print('Uso: puxar_historico_vendedor.py "Nome do Vendedor" [meses=12]', file=sys.stderr)
        sys.exit(1)

    nome_alvo = sys.argv[1]
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 12

    print(f'Buscando historico de "{nome_alvo}" — ultimos {meses} meses...\n')

    client = ContaAzulClient()

    # 1) Acha o ID do vendedor
    vendedores = client.get('/venda/vendedores')
    vid = next((v['id'] for v in vendedores if v['nome'] == nome_alvo), None)
    if not vid:
        print(f'ERRO: vendedor "{nome_alvo}" nao encontrado.')
        print(f'\nVendedores disponiveis na Conta Azul:')
        for v in vendedores:
            print(f'  - {v.get("nome")}')
        sys.exit(1)

    print(f'Vendedor encontrado (id: {vid[:8]}...)')
    print('Consultando mes a mes (pode demorar ~30s)...\n')

    # 2) Itera N meses pra tras
    hoje = datetime.now()
    resultados = []

    for i in range(meses):
        mes_year = hoje.year
        mes_month = hoje.month - i
        while mes_month < 1:
            mes_month += 12
            mes_year -= 1

        primeiro = f'{mes_year:04d}-{mes_month:02d}-01'
        ultimo_n = calendar.monthrange(mes_year, mes_month)[1]
        ultimo  = f'{mes_year:04d}-{mes_month:02d}-{ultimo_n:02d}'

        total = 0.0
        qtd = 0
        pagina = 1
        while True:
            res = client.get('/venda/busca',
                ids_vendedores=[vid],
                data_inicio=primeiro,
                data_fim=ultimo,
                totais='APPROVED',
                pagina=pagina,
                tamanho_pagina=500)
            vendas = res.get('itens', []) if isinstance(res, dict) else []
            if not vendas:
                break
            for v in vendas:
                total += v.get('total', 0) or 0
                qtd += 1
            if len(vendas) < 500:
                break
            pagina += 1

        resultados.append({
            'mes': f'{mes_year}-{mes_month:02d}',
            'total': total,
            'vendas': qtd,
        })
        print(f'  {mes_year}-{mes_month:02d}: {fmt_brl(total):>16} ({qtd} vendas)')

    # 3) Tabela final ordenada
    resultados.sort(key=lambda x: x['mes'])
    print()
    print(f'{"Mes":<10} {"Total":>16} {"Vendas":>8}')
    print('-' * 36)
    grand_total = 0
    grand_vendas = 0
    for r in resultados:
        print(f'{r["mes"]:<10} {fmt_brl(r["total"]):>16} {r["vendas"]:>8}')
        grand_total += r['total']
        grand_vendas += r['vendas']
    print('-' * 36)
    print(f'{"TOTAL":<10} {fmt_brl(grand_total):>16} {grand_vendas:>8}')
    print(f'\nMedia mensal: {fmt_brl(grand_total/max(len(resultados),1))}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Lista de reativacao: clientes de um vendedor que estao em silencio.

Busca as vendas (sale-level, sem itens — leve) dos ultimos N meses, agrupa
por cliente e lista quem nao compra ha pelo menos D dias — ordenado por
valor historico (maior oportunidade primeiro).

Uso:
    python3 lista_reativacao.py "Róger Silva" [meses=12] [dias_min=45]

Saida: relatorio legivel + bloco JSON entre ===JSON=== / ===FIM===
(parseavel a partir do log do GitHub Actions).
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

# Mesmos aliases do atualizar_dados.py — Roger tem 2 cadastros na CA
ALIASES = {
    'Erivan Lima':            ['Erivan Lima'],
    'Róger Silva':            ['Róger Silva', 'Roger de Lima silva'],
    'Lucas de Mello Valente': ['Lucas de Mello Valente'],
    'Jalena':                 ['Jalena'],
    'Célio Alex':             ['Célio Alex'],
}


def main():
    nome_alvo = sys.argv[1] if len(sys.argv) > 1 else 'Róger Silva'
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    dias_min = int(sys.argv[3]) if len(sys.argv) > 3 else 45

    nomes_ca = ALIASES.get(nome_alvo, [nome_alvo])
    client = ContaAzulClient()
    vendedores = client.get('/venda/vendedores')
    ids = [v['id'] for v in vendedores if v['nome'] in nomes_ca]
    if not ids:
        print(f'ERRO: vendedor "{nome_alvo}" nao encontrado.')
        for v in vendedores:
            print(f'  - {v.get("nome")}')
        sys.exit(1)
    print(f'Vendedor: {nome_alvo} ({len(ids)} cadastro(s) na CA)')

    hoje = datetime.now(MANAUS_TZ).replace(tzinfo=None)
    a, m = hoje.year, hoje.month
    for _ in range(meses - 1):
        m -= 1
        if m < 1:
            m, a = 12, a - 1
    data_inicio = f'{a:04d}-{m:02d}-01'
    data_fim = hoje.strftime('%Y-%m-%d')
    print(f'Janela: {data_inicio} a {data_fim} | silencio minimo: {dias_min} dias\n')

    clientes = defaultdict(lambda: {'total': 0.0, 'compras': 0, 'ultima': None, 'primeira': None})
    pagina = 1
    while True:
        res = client.get('/venda/busca',
                         ids_vendedores=ids,
                         data_inicio=data_inicio,
                         data_fim=data_fim,
                         totais='APPROVED',
                         pagina=pagina,
                         tamanho_pagina=500)
        vendas = res.get('itens', []) if isinstance(res, dict) else []
        if not vendas:
            break
        for v in vendas:
            try:
                dt = datetime.strptime(v['data'], '%Y-%m-%d')
            except (KeyError, ValueError):
                continue
            nome_c = ((v.get('cliente') or {}).get('nome') or '?').strip()
            c = clientes[nome_c]
            c['total'] += v.get('total', 0) or 0
            c['compras'] += 1
            if c['ultima'] is None or dt > c['ultima']:
                c['ultima'] = dt
            if c['primeira'] is None or dt < c['primeira']:
                c['primeira'] = dt
        if len(vendas) < 500:
            break
        pagina += 1

    print(f'{len(clientes)} cliente(s) unicos na janela')

    lista = []
    for nome_c, c in clientes.items():
        dias = (hoje.date() - c['ultima'].date()).days
        if dias < dias_min:
            continue
        lista.append({
            'cliente': nome_c,
            'ultima_compra': c['ultima'].strftime('%d/%m/%Y'),
            'dias_silencio': dias,
            'compras': c['compras'],
            'total': round(c['total'], 2),
            'ticket_medio': round(c['total'] / max(c['compras'], 1), 2),
        })
    lista.sort(key=lambda x: -x['total'])

    print(f'{len(lista)} cliente(s) em silencio (>= {dias_min} dias)\n')
    for x in lista[:60]:
        print(f"  {x['dias_silencio']:>4}d | {x['cliente'][:45]:<45} | "
              f"{x['compras']:>3}x | R$ {x['total']:>10,.2f}")

    print('\n===JSON===')
    print(json.dumps({'vendedor': nome_alvo, 'gerado_em': hoje.strftime('%d/%m/%Y'),
                      'janela_meses': meses, 'dias_min': dias_min, 'clientes': lista},
                     ensure_ascii=False))
    print('===FIM===')


if __name__ == '__main__':
    main()

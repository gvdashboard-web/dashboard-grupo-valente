#!/usr/bin/env python3
"""Busca vendas de um PRODUTO (trecho do nome) numa janela de N meses.

Varre as vendas dos vendedores monitorados, abre os itens e seleciona os que
casam com o termo. Agrega por ano, mes, modelo, marca e cliente.

Valores em base BRUTA por item (preco_unit * qtd) — mesma base dos rankings
de produto/marca do dashboard. Desconto e no nivel da venda, nao rateavel
por item.

Uso:
    python3 busca_produto.py "cadeira" [meses=36]
"""
import calendar
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from ca_client import ContaAzulClient
from gerar_relatorio import categorizar
from atualizar_dados import inferir_marca, VENDOR_FULL_NAMES

MANAUS_TZ = timezone(timedelta(hours=-4))
SELLER_NAMES = {
    'Erivan Lima': 'erivan', 'Lucas de Mello Valente': 'lucas',
    'Róger Silva': 'roger', 'Roger de Lima silva': 'roger',
    'Jalena': 'jalena', 'Célio Alex': 'celio',
}


def norm(s):
    s = unicodedata.normalize('NFKD', (s or '').upper())
    return ''.join(c for c in s if not unicodedata.combining(c))


def main():
    termo = sys.argv[1] if len(sys.argv) > 1 else 'cadeira'
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 36
    alvo = norm(termo)

    client = ContaAzulClient()
    vendedores = client.get('/venda/vendedores')
    id_to_key = {v['id']: SELLER_NAMES[v['nome']] for v in vendedores if v['nome'] in SELLER_NAMES}
    ids = list(id_to_key)
    print(f'Busca de produto: "{termo}" | {meses} meses | {len(ids)} vendedor(es)\n', flush=True)

    hoje = datetime.now(MANAUS_TZ).replace(tzinfo=None)
    janela = []
    a, m = hoje.year, hoje.month
    for _ in range(meses):
        janela.append((a, m))
        m -= 1
        if m < 1:
            m, a = 12, a - 1
    janela.reverse()

    achados = []
    por_mes = defaultdict(lambda: {'v': 0.0, 'q': 0})
    por_modelo = defaultdict(lambda: {'v': 0.0, 'q': 0})
    por_cliente = defaultdict(lambda: {'v': 0.0, 'q': 0})
    por_marca = defaultdict(float)
    por_vend = defaultdict(float)
    movelaria_mes = defaultdict(float)   # contexto: categoria Movelaria inteira
    vendas_vistas = 0

    for ano_b, mes_b in janela:
        ym = f'{ano_b:04d}-{mes_b:02d}'
        primeiro = f'{ym}-01'
        ultimo = f'{ym}-{calendar.monthrange(ano_b, mes_b)[1]:02d}'
        achou_mes = 0
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
                    vendas_vistas += 1
                    try:
                        ir = client.get(f"/venda/{v['id']}/itens", tamanho_pagina=200)
                        itens = ir.get('itens', []) if isinstance(ir, dict) else []
                    except Exception as e:
                        print(f"    aviso: itens da venda {v.get('numero')}: {e}", flush=True)
                        continue
                    cliente = ((v.get('cliente') or {}).get('nome') or '?').strip()
                    vend = VENDOR_FULL_NAMES.get(id_to_key.get(vid, ''), '?')
                    for it in itens:
                        prod = it.get('nome', '')
                        q = int(it.get('quantidade', 0) or 0)
                        val = (it.get('valor', 0) or 0) * q
                        if categorizar(prod) == 'Movelaria':
                            movelaria_mes[ym] += val
                        if alvo not in norm(prod):
                            continue
                        achou_mes += 1
                        por_mes[ym]['v'] += val; por_mes[ym]['q'] += q
                        por_modelo[prod]['v'] += val; por_modelo[prod]['q'] += q
                        por_cliente[cliente]['v'] += val; por_cliente[cliente]['q'] += q
                        por_marca[inferir_marca(prod)] += val
                        por_vend[vend] += val
                        achados.append({'data': v.get('data'), 'cliente': cliente,
                                        'vendedor': vend, 'produto': prod, 'q': q,
                                        'v': round(val, 2)})
                if len(vendas) < 500:
                    break
                pagina += 1
        print(f'  {ym}: {achou_mes} item(ns) de "{termo}"'
              + (f' | R$ {por_mes[ym]["v"]:,.2f}' if ym in por_mes else ''), flush=True)

    total_v = sum(d['v'] for d in por_mes.values())
    total_q = sum(d['q'] for d in por_mes.values())
    print(f'\n{vendas_vistas} vendas varridas | {len(achados)} itens de "{termo}"')
    print(f'TOTAL: {total_q} unidade(s) | R$ {total_v:,.2f}')

    por_ano = defaultdict(lambda: {'v': 0.0, 'q': 0})
    for ym, d in por_mes.items():
        por_ano[ym[:4]]['v'] += d['v']; por_ano[ym[:4]]['q'] += d['q']
    print('\nPor ano:')
    for y in sorted(por_ano):
        d = por_ano[y]
        print(f"  {y}: {d['q']:>4} un | R$ {d['v']:>12,.2f}")

    print('\nModelos:')
    for p, d in sorted(por_modelo.items(), key=lambda kv: -kv[1]['v']):
        print(f"  {p[:52]:<52} {d['q']:>4}un R$ {d['v']:>11,.2f}")

    print('\nTop clientes:')
    for cnome, d in sorted(por_cliente.items(), key=lambda kv: -kv[1]['v'])[:12]:
        print(f"  {cnome[:44]:<44} {d['q']:>3}un R$ {d['v']:>10,.2f}")

    print('\n===JSON===')
    print(json.dumps({
        'termo': termo, 'gerado_em': hoje.strftime('%d/%m/%Y'),
        'meses': [f'{a:04d}-{m:02d}' for a, m in janela],
        'vendas_varridas': vendas_vistas,
        'total_valor': round(total_v, 2), 'total_qtd': total_q,
        'por_ano': {y: {'v': round(d['v'], 2), 'q': d['q']} for y, d in por_ano.items()},
        'por_mes': {k: {'v': round(d['v'], 2), 'q': d['q']} for k, d in por_mes.items()},
        'por_modelo': [[p, round(d['v'], 2), d['q']] for p, d in
                       sorted(por_modelo.items(), key=lambda kv: -kv[1]['v'])],
        'por_cliente': [[c, round(d['v'], 2), d['q']] for c, d in
                        sorted(por_cliente.items(), key=lambda kv: -kv[1]['v'])[:30]],
        'por_marca': sorted([[k, round(v, 2)] for k, v in por_marca.items()], key=lambda x: -x[1]),
        'por_vendedor': {k: round(v, 2) for k, v in por_vend.items()},
        'movelaria_mes': {k: round(v, 2) for k, v in movelaria_mes.items()},
        'itens': achados,
    }, ensure_ascii=False))
    print('===FIM===')


if __name__ == '__main__':
    main()

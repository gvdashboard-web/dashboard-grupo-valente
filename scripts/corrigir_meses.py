#!/usr/bin/env python3
"""Recalcula meses FECHADOS no historico do index.html com o valor real.

Um mes fechado no dashboard herda o ultimo valor de projecao (o roll congela
o ponto na virada). Como o dado da Conta Azul chega em bloco D-1, esse valor
costuma ser uma estimativa, nao o fechamento real. Este script busca os itens
do mes na API, calcula o LIQUIDO e reescreve os pontos de historico_total e
historico_vendedor.

Meses com `projecao:true` (mes corrente) sao apenas reportados, nunca
sobrescritos — quem manda neles e o run normal do cron.

Uso:
    python3 corrigir_meses.py 2026-06 2026-07 [--target index.html]
"""
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from ca_client import ContaAzulClient
from atualizar_dados import fetch_items_from_ca, aggregate, VENDOR_FULL_NAMES


def fmt(v):
    return f'{v:,.2f}'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    target = Path('index.html')
    if '--target' in sys.argv:
        target = Path(sys.argv[sys.argv.index('--target') + 1])
    meses = [a for a in args if re.fullmatch(r'\d{4}-\d{2}', a)]
    if not meses:
        print('Uso: corrigir_meses.py YYYY-MM [YYYY-MM ...]', file=sys.stderr)
        sys.exit(1)

    html = target.read_text()
    client = ContaAzulClient()
    mudou = False

    for ms in meses:
        ano, mes = int(ms[:4]), int(ms[5:7])
        print(f'\n=== {ms} ===')
        pat_tot = re.compile(r'(\{mes:"' + ms + r'",vlr_bruto:)([\d.]+)(,projecao:true)?(\})')
        m_tot = pat_tot.search(html)
        if not m_tot:
            print('  ponto nao existe no historico — pulando')
            continue
        is_proj = bool(m_tot.group(3))

        items = fetch_items_from_ca(ano, mes, client=client)
        agg = aggregate(items)
        real_total = agg['total']
        antigo = float(m_tot.group(2))
        delta = real_total - antigo
        print(f'  dashboard: R$ {fmt(antigo)} | real (liquido): R$ {fmt(real_total)} '
              f'| dif: R$ {fmt(delta)} ({delta/max(antigo,1)*100:+.1f}%)')

        if is_proj:
            print('  mes CORRENTE (projecao) — nao sobrescrevo; o cron cuida disso')
            continue

        html = pat_tot.sub(lambda mm: mm.group(1) + f'{real_total:.2f}' + (mm.group(3) or '') + mm.group(4),
                           html, count=1)
        mudou = True

        # por vendedor — so dentro da secao historico_vendedor
        m_sec = re.search(r'historico_vendedor:\s*\{', html)
        i = m_sec.end() - 1
        depth = 0
        for j in range(i, len(html)):
            if html[j] == '{':
                depth += 1
            elif html[j] == '}':
                depth -= 1
                if depth == 0:
                    fim = j + 1
                    break
        sec = html[i:fim]
        for nome in VENDOR_FULL_NAMES.values():
            real_v = agg['vendedores'].get(nome, {}).get('fat', 0.0)
            pat_v = re.compile(r'("' + re.escape(nome) + r'":\s*\[[^\]]*\{mes:"' + ms + r'",vlr_bruto:)([\d.]+)(,projecao:true)?(\})',
                               re.DOTALL)
            mv = pat_v.search(sec)
            if not mv:
                continue
            ant_v = float(mv.group(2))
            sec = pat_v.sub(lambda mm: mm.group(1) + f'{real_v:.2f}' + (mm.group(3) or '') + mm.group(4),
                            sec, count=1)
            if abs(real_v - ant_v) >= 0.01:
                print(f'    {nome[:24]:<24} {fmt(ant_v):>12} -> {fmt(real_v):>12}')
        html = html[:i] + sec + html[fim:]

    if mudou:
        target.write_text(html)
        print('\nindex.html atualizado.')
    else:
        print('\nNada a alterar.')


if __name__ == '__main__':
    main()

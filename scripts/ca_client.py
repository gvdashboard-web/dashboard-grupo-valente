#!/usr/bin/env python3
"""Cliente da API Conta Azul — modulo reutilizavel.

Gerencia tokens (le do Keychain, renova automaticamente via refresh_token)
e fornece metodos pra chamar endpoints da API.
"""
import base64
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

TOKEN_URL = 'https://auth.contaazul.com/oauth2/token'
API_BASE = 'https://api-v2.contaazul.com/v1'
USER = 'lucasvalente'

# Em CI (GitHub Actions) lemos credenciais de env vars; localmente do Keychain.
IS_CI = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'


def keychain_get(service):
    """Le do Keychain (Mac) — usado em ambiente local."""
    try:
        result = subprocess.run(
            ['security', 'find-generic-password', '-a', USER, '-s', service, '-w'],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def keychain_set(service, value):
    """Salva no Keychain (Mac) — usado em ambiente local."""
    try:
        subprocess.run(
            ['security', 'delete-generic-password', '-a', USER, '-s', service],
            capture_output=True
        )
        subprocess.run(
            ['security', 'add-generic-password', '-a', USER, '-s', service, '-w', value],
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # CI nao tem keychain, ok


def cred_get(env_var, keychain_service):
    """Le credencial de env var (CI) ou Keychain (local)."""
    if IS_CI:
        return os.environ.get(env_var)
    return keychain_get(keychain_service)


def cred_set(env_var, keychain_service, value):
    """Salva no Keychain. Em CI nao salva (env vars sao read-only)."""
    if not IS_CI:
        keychain_set(keychain_service, value)


class ContaAzulClient:
    def __init__(self):
        # .strip() pra remover qualquer espaco/newline acidental
        self.client_id = (cred_get('CA_CLIENT_ID', 'contaazul-client-id') or '').strip()
        self.client_secret = (cred_get('CA_CLIENT_SECRET', 'contaazul-client-secret') or '').strip()
        self.refresh_token = (cred_get('CA_REFRESH_TOKEN', 'contaazul-refresh-token') or '').strip()
        self.access_token = (cred_get('CA_ACCESS_TOKEN', 'contaazul-access-token') or '').strip()

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            origem = 'env vars (CA_CLIENT_ID, CA_CLIENT_SECRET, CA_REFRESH_TOKEN)' if IS_CI else 'Keychain'
            raise RuntimeError(
                f'Credenciais incompletas em {origem}. Rode `auth_contaazul.py` primeiro.'
            )

        # Log de debug (so em CI, pra entender o que ta acontecendo)
        if IS_CI:
            print(f'[ca_client] client_id len={len(self.client_id)}, '
                  f'secret len={len(self.client_secret)}, '
                  f'refresh len={len(self.refresh_token)}', file=sys.stderr)

    def _refresh(self):
        """Renova access_token usando refresh_token."""
        auth_header = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode()
        ).decode()
        body = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
        }).encode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                tokens = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            raise RuntimeError(
                f'Refresh token falhou — HTTP {e.code}: {err_body[:500]}'
            ) from e

        self.access_token = tokens['access_token']
        cred_set('CA_ACCESS_TOKEN', 'contaazul-access-token', self.access_token)
        # Conta Azul rotaciona o refresh_token a cada uso — precisamos persistir o novo
        if 'refresh_token' in tokens and tokens['refresh_token'] != self.refresh_token:
            self.refresh_token = tokens['refresh_token']
            cred_set('CA_REFRESH_TOKEN', 'contaazul-refresh-token', self.refresh_token)
            if IS_CI:
                # O token NUNCA pode aparecer em log: o repo e publico e refresh
                # token vazado + usado por terceiro revoga a familia toda no
                # Cognito (invalid_grant em loop). ::add-mask:: cobre qualquer
                # ocorrencia futura no log, inclusive o display de env de steps.
                print(f'::add-mask::{self.refresh_token}')
                sys.stdout.flush()

                # Persiste o secret JA, sem depender de step posterior do
                # workflow — se o job crashar depois daqui o secret ja esta novo.
                pat = os.environ.get('SECRETS_PAT')
                repo = os.environ.get('GITHUB_REPOSITORY')
                if pat and repo:
                    try:
                        from update_github_secret import update_secret
                        update_secret(pat, repo, 'CA_REFRESH_TOKEN', self.refresh_token)
                        print('[ca_client] Secret CA_REFRESH_TOKEN atualizado (inline)', file=sys.stderr)
                    except Exception as e:
                        print(f'[ca_client] AVISO: persist inline falhou: {e}', file=sys.stderr)

                # Fallback: GITHUB_ENV pro step "Persistir" do workflow
                github_env = os.environ.get('GITHUB_ENV')
                if github_env:
                    with open(github_env, 'a') as f:
                        f.write(f'NEW_REFRESH_TOKEN={self.refresh_token}\n')
                    print('[ca_client] Novo refresh_token escrito em GITHUB_ENV', file=sys.stderr)
        return self.access_token

    def _request(self, method, path, params=None, body=None, _retry=True):
        """Faz request autenticado. Renova token automaticamente em 401."""
        url = API_BASE + path
        if params:
            # doseq=True serializa listas como ?key=v1&key=v2 (padrao OAS array)
            url += '?' + urllib.parse.urlencode(params, doseq=True)

        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method=method
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read().decode()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                # Token expirou — renova e tenta de novo
                self._refresh()
                return self._request(method, path, params, body, _retry=False)
            err_body = e.read().decode()
            raise RuntimeError(f'API erro HTTP {e.code}: {err_body[:500]}') from e

    def get(self, path, **params):
        return self._request('GET', path, params=params)

    def post(self, path, body):
        return self._request('POST', path, body=body)


if __name__ == '__main__':
    # Teste rapido: pega lista de vendedores (endpoint mais simples pra validar token)
    client = ContaAzulClient()
    print('Testando chamada à API Conta Azul...\n')

    print('1) Listando vendedores cadastrados (/venda/vendedores)...')
    try:
        result = client.get('/venda/vendedores')
        print(f'   OK! Encontrados {len(result) if isinstance(result, list) else "?"} vendedor(es):')
        print(json.dumps(result, indent=2, ensure_ascii=False)[:1500])
    except Exception as e:
        print(f'   ERRO: {e}')
        sys.exit(1)

    print('\n2) Buscando vendas do mes corrente (/venda/busca)...')
    from datetime import datetime
    now = datetime.now()
    primeiro_dia = f'{now.year:04d}-{now.month:02d}-01'
    try:
        result = client.get('/venda/busca',
                            data_inicio=primeiro_dia,
                            data_fim=now.strftime('%Y-%m-%d'),
                            campo_ordenado_descendente='DATA',
                            totais='APPROVED',
                            pagina=1,
                            tamanho_pagina=10)

        qtd = result.get('quantidades', {}).get('total', '?')
        tot = result.get('totais', {}).get('total', 0)
        print(f'   OK! {qtd} venda(s) no mes | Total: R$ {tot:,.2f}')
        print(f'   Primeiras 3 vendas:')
        itens = result.get('itens', [])[:3]
        for v in itens:
            print(f"     - #{v.get('numero')} | {v.get('data')} | "
                  f"R$ {v.get('total')} | {v.get('cliente',{}).get('nome','?')}")
        # mostra estrutura completa do primeiro
        if itens:
            print('\n   Estrutura do primeiro registro:')
            print(json.dumps(itens[0], indent=2, ensure_ascii=False))
    except Exception as e:
        print(f'   ERRO: {e}')
        sys.exit(1)

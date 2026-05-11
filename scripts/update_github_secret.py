#!/usr/bin/env python3
"""Atualiza um secret de Actions via API GitHub.

Usado dentro do workflow pra persistir o novo refresh_token quando a
Conta Azul rotaciona o token.

Uso:
    GH_TOKEN=ghp_... python3 update_github_secret.py REPO SECRET_NAME SECRET_VALUE

Ex:
    python3 update_github_secret.py gvdashboard-web/dashboard-grupo-valente CA_REFRESH_TOKEN "abc123"
"""
import base64
import json
import os
import sys
import urllib.request
from nacl import encoding, public  # type: ignore  # pip install pynacl


def update_secret(token, repo, secret_name, secret_value):
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    # 1) Pega public key do repo
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/actions/secrets/public-key',
        headers=headers
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        pk_data = json.loads(resp.read().decode())
    key = pk_data['key']
    key_id = pk_data['key_id']

    # 2) Encripta o valor com libsodium sealed_box (padrao do GitHub)
    pk = public.PublicKey(key.encode('utf-8'), encoding.Base64Encoder())
    sealed = public.SealedBox(pk)
    encrypted = sealed.encrypt(secret_value.encode('utf-8'))
    encrypted_b64 = base64.b64encode(encrypted).decode('utf-8')

    # 3) PUT no secret
    body = json.dumps({
        'encrypted_value': encrypted_b64,
        'key_id': key_id,
    }).encode()
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/actions/secrets/{secret_name}',
        data=body,
        headers={**headers, 'Content-Type': 'application/json'},
        method='PUT'
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (201, 204):
            raise RuntimeError(f'PUT secret falhou: HTTP {resp.status}')
    print(f'OK secret {secret_name} atualizado em {repo}')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('Uso: update_github_secret.py REPO SECRET_NAME SECRET_VALUE', file=sys.stderr)
        sys.exit(1)
    repo, name, value = sys.argv[1], sys.argv[2], sys.argv[3]
    token = os.environ.get('GH_TOKEN') or os.environ.get('SECRETS_PAT')
    if not token:
        print('ERRO: defina GH_TOKEN ou SECRETS_PAT no ambiente', file=sys.stderr)
        sys.exit(1)
    update_secret(token, repo, name, value)

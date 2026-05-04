import json, os, requests

TOKEN_URL  = "https://api-v2.contaazul.com/auth/realms/contaazul/protocol/openid-connect/token"
TOKEN_FILE = "tokens.json"


def _inicializar_tokens():
    if not os.path.exists(TOKEN_FILE):
        raw = os.environ.get("CONTA_AZUL_TOKENS", "")
        if raw:
            with open(TOKEN_FILE, "w") as f:
                f.write(raw)
            print("[AUTH] tokens.json restaurado da env var.")

_inicializar_tokens()


def _ler() -> dict:
    with open(TOKEN_FILE) as f:
        return json.load(f)


def _salvar(tokens: dict):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def get_access_token() -> str:
    from config import CONTA_AZUL_CLIENT_ID, CONTA_AZUL_CLIENT_SECRET

    tokens = _ler()

    # Valida token atual
    r = requests.get(
        "https://api-v2.contaazul.com/v1/financeiro/contas-financeiras",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        params={"pagina": 1, "tamanho_pagina": 1},
        timeout=10,
    )
    if r.status_code != 401:
        return tokens["access_token"]

    # Renova
    print("[AUTH] Renovando token...")
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "client_id":     CONTA_AZUL_CLIENT_ID,
        "client_secret": CONTA_AZUL_CLIENT_SECRET,
        "refresh_token": tokens["refresh_token"],
    }, timeout=15)
    r.raise_for_status()
    novos = r.json()
    _salvar(novos)
    print("[AUTH] Token renovado.")
    return novos["access_token"]

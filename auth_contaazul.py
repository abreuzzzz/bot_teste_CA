import os, json, base64, time, requests
from config import CONTA_AZUL_CLIENT_ID, CONTA_AZUL_CLIENT_SECRET

AUTH_TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
TOKEN_FILE     = "tokens.json"


def _salvar_tokens(access_token: str, refresh_token: str, expires_at: float):
    data = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "expires_at":    expires_at,
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)

    # Se estiver rodando no GitHub Actions, persiste o secret imediatamente
    _persistir_secret_github(json.dumps(data))


def _persistir_secret_github(tokens_json: str):
    gh_token = os.environ.get("GH_TOKEN")
    repo     = os.environ.get("GH_REPO")
    if not gh_token or not repo:
        return  # rodando local, ignora
    try:
        from nacl import encoding, public

        headers = {
            "Authorization": f"Bearer {gh_token}",
            "Accept":        "application/vnd.github+json",
        }
        pub = requests.get(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers, timeout=10,
        ).json()

        pk        = public.PublicKey(pub["key"].encode(), encoding.Base64Encoder())
        encrypted = base64.b64encode(
            public.SealedBox(pk).encrypt(tokens_json.encode())
        ).decode()

        requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/CONTA_AZUL_TOKENS",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pub["key_id"]},
            timeout=10,
        ).raise_for_status()
        print("[AUTH] Token persistido no GitHub Secret.")
    except Exception as e:
        print(f"[AUTH] Aviso: não foi possível persistir no secret: {e}")


def _carregar_tokens() -> dict:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    raw = os.environ.get("CONTA_AZUL_TOKENS")
    if raw:
        data = json.loads(raw)
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f)
        return data
    raise RuntimeError("Tokens não encontrados. Execute o workflow first_auth primeiro.")


def _renovar_token(refresh_token: str) -> dict:
    b64 = base64.b64encode(
        f"{CONTA_AZUL_CLIENT_ID}:{CONTA_AZUL_CLIENT_SECRET}".encode()
    ).decode()
    resp = requests.post(
        AUTH_TOKEN_URL,
        headers={
            "Authorization": f"Basic {b64}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     CONTA_AZUL_CLIENT_ID,
            "client_secret": CONTA_AZUL_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_access_token() -> str:
    tokens = _carregar_tokens()

    if time.time() < tokens["expires_at"] - 300:
        return tokens["access_token"]

    print("[AUTH] Renovando token...")
    novo       = _renovar_token(tokens["refresh_token"])
    expires_at = time.time() + novo["expires_in"]
    _salvar_tokens(novo["access_token"], novo["refresh_token"], expires_at)
    print("[AUTH] Token renovado.")
    return novo["access_token"]

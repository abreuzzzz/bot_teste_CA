import os, json, base64, time, requests
from config import CONTA_AZUL_CLIENT_ID, CONTA_AZUL_CLIENT_SECRET

AUTH_TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
TOKEN_FILE     = "tokens.json"


def _salvar_tokens(access_token: str, refresh_token: str, expires_at: float):
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "expires_at":    expires_at,
        }, f)


def _carregar_tokens() -> dict:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    raw = os.environ.get("CONTA_AZUL_TOKENS")
    if raw:
        data = json.loads(raw)
        _salvar_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
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

    # Ainda válido (com margem de 5 min)
    if time.time() < tokens["expires_at"] - 300:
        return tokens["access_token"]

    # Renova
    print("[AUTH] Renovando token...")
    novo       = _renovar_token(tokens["refresh_token"])
    expires_at = time.time() + novo["expires_in"]
    _salvar_tokens(novo["access_token"], novo["refresh_token"], expires_at)
    print("[AUTH] Token renovado.")
    return novo["access_token"]


def get_tokens_json_str() -> str:
    """Retorna conteúdo atual de tokens.json como string (para salvar no secret)."""
    with open(TOKEN_FILE) as f:
        return f.read()

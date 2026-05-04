"""Persistência simples de JSON com fallback opcional para GitHub Secret."""
import os, json, base64, requests
from typing import Any


def _persistir_secret_github(nome_secret: str, conteudo: str) -> None:
    gh_token = os.environ.get("GH_TOKEN")
    repo     = os.environ.get("GH_REPO")
    if not gh_token or not repo:
        return
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
            public.SealedBox(pk).encrypt(conteudo.encode())
        ).decode()
        requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{nome_secret}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pub["key_id"]},
            timeout=10,
        ).raise_for_status()
        print(f"[STORAGE] Secret {nome_secret} atualizado.")
    except Exception as e:
        print(f"[STORAGE] Aviso: não persistiu {nome_secret}: {e}")


def carregar(arquivo: str, env_var: str | None = None, default: Any = None) -> Any:
    if os.path.exists(arquivo):
        try:
            with open(arquivo, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if env_var and os.environ.get(env_var):
        try:
            data = json.loads(os.environ[env_var])
            with open(arquivo, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return data
        except Exception:
            pass
    return default if default is not None else {}


def salvar(arquivo: str, data: Any, secret_name: str | None = None) -> None:
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    with open(arquivo, "w", encoding="utf-8") as f:
        f.write(raw)
    if secret_name:
        _persistir_secret_github(secret_name, json.dumps(data, ensure_ascii=False))

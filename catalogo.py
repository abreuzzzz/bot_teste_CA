import time, requests
from auth_contaazul import get_access_token

BASE = "https://api-v2.contaazul.com/v1/financeiro"
_cache: dict = {}
_TTL = 3600


def _h():
    return {"Authorization": f"Bearer {get_access_token()}"}


def _buscar(endpoint: str, params_extra: dict = {}) -> list:
    itens, pagina = [], 1
    while True:
        r = requests.get(
            f"{BASE}/{endpoint}",
            headers=_h(),
            params={"pagina": pagina, "tamanho_pagina": 200, **params_extra},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("itens") or (data if isinstance(data, list) else [])
        itens += batch
        if len(itens) >= data.get("itens_totais", len(itens)):
            break
        pagina += 1
    return itens


def _get(chave: str, fn) -> list:
    e = _cache.get(chave)
    if e and (time.time() - e["ts"]) < _TTL:
        return e["data"]
    dados = fn()
    _cache[chave] = {"data": dados, "ts": time.time()}
    return dados


def invalidar_cache():
    _cache.clear()


def contas_financeiras() -> list:
    return _get("contas", lambda: _buscar("contas-financeiras"))


def categorias_receita() -> list:
    return _get("cat_rec", lambda: _buscar("categorias", {"tipo": "RECEITA"}))


def categorias_despesa() -> list:
    return _get("cat_des", lambda: _buscar("categorias", {"tipo": "DESPESA"}))


def centros_custo() -> list:
    return _get("centros", lambda: _buscar("centros-custo"))

import time, requests
from auth_contaazul import get_access_token
import storage as _storage

BASE = "https://api-v2.contaazul.com/v1"

_cache: dict = {}
_TTL = 3600  # 1 hora
_CACHE_FILE = "catalogo_cache.json"


def _h() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def _buscar_paginado(endpoint: str, params_extra: dict = {}) -> list:
    """Busca todos os itens paginando automaticamente."""
    url    = f"{BASE}/{endpoint}"
    itens  = []
    pagina = 1

    while True:
        r = requests.get(
            url,
            headers=_h(),
            params={"pagina": pagina, "tamanho_pagina": 200, **params_extra},
            timeout=15,
        )
        print(f"[CATALOGO] GET {url} (pág {pagina}) → HTTP {r.status_code}")

        if r.status_code == 404:
            print(f"[CATALOGO] Endpoint não encontrado: {url}")
            return []

        r.raise_for_status()
        data  = r.json()

        # A API retorna "itens" ou lista direta
        batch = data.get("itens") or data.get("items") or (data if isinstance(data, list) else [])
        itens += batch

        total = data.get("itens_totais", len(itens))
        if len(itens) >= total:
            break
        pagina += 1

    return itens


def _get(chave: str, fn) -> list:
    entrada = _cache.get(chave)
    if entrada and (time.time() - entrada["ts"]) < _TTL:
        return entrada["data"]
    dados = fn()
    _cache[chave] = {"data": dados, "ts": time.time()}
    _save_cache()
    return dados


def _save_cache():
    """Persiste o cache atual em disco."""
    try:
        _storage.salvar(_CACHE_FILE, _cache)
    except Exception as e:
        print(f"[CATALOGO] Aviso: não salvou cache em disco: {e}")


def _load_cache():
    """Carrega cache do disco ao iniciar (respeita TTL)."""
    data = _storage.carregar(_CACHE_FILE)
    if isinstance(data, dict):
        _cache.update(data)
        print(f"[CATALOGO] Cache carregado do disco ({len(data)} entradas).")


def invalidar_cache():
    _cache.clear()
    try:
        import os; os.remove(_CACHE_FILE)
    except Exception:
        pass
    print("[CATALOGO] Cache invalidado.")


def contas_financeiras() -> list:
    # GET /v1/conta-financeira
    return _get("contas", lambda: _buscar_paginado("conta-financeira", {"apenas_ativo": "true"}))


def categorias_receita() -> list:
    # GET /v1/categorias?tipo=RECEITA
    return _get("cat_rec", lambda: _buscar_paginado("categorias", {
        "tipo":                "RECEITA",
        "permite_apenas_filhos": "true",
    }))


def categorias_despesa() -> list:
    # GET /v1/categorias?tipo=DESPESA
    return _get("cat_des", lambda: _buscar_paginado("categorias", {
        "tipo":                "DESPESA",
        "permite_apenas_filhos": "true",
    }))


def centros_custo() -> list:
    # GET /v1/centro-de-custo
    return _get("centros", lambda: _buscar_paginado("centro-de-custo", {"filtro_rapido": "ATIVO"}))


def categorias_dre() -> list:
    # GET /v1/financeiro/categorias-dre
    return _get("dre", lambda: _buscar_paginado("financeiro/categorias-dre"))


# Carrega cache do disco ao importar o módulo
_load_cache()

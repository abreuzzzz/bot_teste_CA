"""Lançamentos favoritos (templates) — Feature 11."""
import storage as _storage

_ARQUIVO = "favoritos.json"
_SECRET  = "FAVORITOS_DATA"


def _carregar() -> dict:
    return _storage.carregar(_ARQUIVO, _SECRET, default={})


def _salvar(data: dict):
    _storage.salvar(_ARQUIVO, data, secret_name=_SECRET)


def salvar_favorito(nome: str, dados: dict) -> None:
    """Salva um template com o nome dado."""
    favs = _carregar()
    favs[nome.lower().strip()] = dados
    _salvar(favs)


def remover_favorito(nome: str) -> bool:
    favs = _carregar()
    chave = nome.lower().strip()
    if chave not in favs:
        return False
    del favs[chave]
    _salvar(favs)
    return True


def listar() -> dict:
    return _carregar()


def obter(nome: str) -> dict | None:
    return _carregar().get(nome.lower().strip())

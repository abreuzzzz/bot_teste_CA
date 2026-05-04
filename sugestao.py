from difflib import SequenceMatcher
from catalogo import (
    contas_financeiras, categorias_receita,
    categorias_despesa, centros_custo,
)


def _score(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if b in a or a in b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def top3(lista: list, termo: str, boost_nome: str = "") -> list:
    scored = []
    for item in lista:
        s = _score(termo, item.get("nome", ""))
        if boost_nome and boost_nome.lower() in item.get("nome", "").lower():
            s = min(s + 0.5, 1.0)
        scored.append((item, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [i for i, s in scored[:3] if s > 0.05]


def match_livre(lista: list, texto: str) -> dict | None:
    scored = [(i, _score(texto, i.get("nome", ""))) for i in lista]
    scored.sort(key=lambda x: x[1], reverse=True)
    melhor, score = scored[0] if scored else (None, 0)
    return melhor if score >= 0.35 else None


def sugerir_conta(termo: str) -> list:
    from config import BOOST_CONTA
    return top3(contas_financeiras(), termo, BOOST_CONTA)


def sugerir_categoria(termo: str, tipo: str) -> list:
    from config import BOOST_CATEGORIA_RECEITA, BOOST_CATEGORIA_DESPESA
    if tipo == "RECEBER":
        return top3(categorias_receita(), termo, BOOST_CATEGORIA_RECEITA)
    return top3(categorias_despesa(), termo, BOOST_CATEGORIA_DESPESA)


def sugerir_centro(termo: str) -> list:
    return top3(centros_custo(), termo)

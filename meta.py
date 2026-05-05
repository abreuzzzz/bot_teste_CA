"""Meta de faturamento mensal."""
import json, os
from datetime import date

_FILE = "metas.json"


def _carregar() -> dict:
    if not os.path.exists(_FILE):
        return {}
    try:
        return json.load(open(_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _salvar(dados: dict):
    json.dump(dados, open(_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def definir_meta(chat_id: int, valor: float, tipo: str = "receita"):
    """Define meta mensal. tipo = 'receita' | 'resultado'."""
    dados = _carregar()
    dados[str(chat_id)] = {"valor": valor, "tipo": tipo}
    _salvar(dados)


def get_meta(chat_id: int) -> dict | None:
    dados = _carregar()
    return dados.get(str(chat_id))


def remover_meta(chat_id: int):
    dados = _carregar()
    dados.pop(str(chat_id), None)
    _salvar(dados)


def progresso(chat_id: int) -> dict | None:
    """
    Retorna progresso da meta do mês atual.
    {meta_valor, realizado, pct, tipo, faltam, projecao_fim_mes}
    """
    from consulta_financeira import resumo_mes
    meta = get_meta(chat_id)
    if not meta:
        return None
    resumo    = resumo_mes()
    tipo      = meta.get("tipo", "receita")
    meta_v    = meta["valor"]
    realizado = resumo["recebido"] if tipo == "receita" else resumo["resultado"]
    pct       = (realizado / meta_v * 100) if meta_v else 0

    # Projeção: dias passados / dias no mês * realizado
    hoje  = date.today()
    dias_mes   = (date(hoje.year + (1 if hoje.month == 12 else 0),
                        (hoje.month % 12) + 1, 1) - date(hoje.year, hoje.month, 1)).days
    dias_pass  = hoje.day
    projecao   = (realizado / dias_pass * dias_mes) if dias_pass else 0

    return {
        "meta_valor":    round(meta_v, 2),
        "realizado":     round(realizado, 2),
        "pct":           round(pct, 1),
        "tipo":          tipo,
        "faltam":        round(max(meta_v - realizado, 0), 2),
        "projecao_fim":  round(projecao, 2),
        "dias_pass":     dias_pass,
        "dias_mes":      dias_mes,
    }


def barra_progresso(pct: float, tamanho: int = 10) -> str:
    cheios = min(int(round(pct / 100 * tamanho)), tamanho)
    return "█" * cheios + "░" * (tamanho - cheios)

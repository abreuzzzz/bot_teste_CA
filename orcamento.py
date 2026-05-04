"""Orçamento mensal por categoria de despesa, com alertas de 80% e 100%."""
from datetime import date
from storage import carregar, salvar
from consulta_financeira import _buscar, _valor_pago, _valor, STATUS_RECEBIDO

ARQUIVO     = "orcamento.json"
ENV_VAR     = "ORCAMENTO_DATA"
SECRET_NAME = "ORCAMENTO_DATA"


def _load() -> dict:
    """{ 'categorias': {nome: limite}, 'alertas_enviados': {YYYY-MM:{nome:nivel}} }"""
    d = carregar(ARQUIVO, ENV_VAR, default={})
    d.setdefault("categorias", {})
    d.setdefault("alertas_enviados", {})
    return d


def _save(d: dict) -> None:
    salvar(ARQUIVO, d, secret_name=SECRET_NAME)


def definir(categoria: str, limite: float) -> None:
    d = _load()
    d["categorias"][categoria.lower().strip()] = float(limite)
    _save(d)


def remover(categoria: str) -> bool:
    d = _load()
    chave = categoria.lower().strip()
    if chave in d["categorias"]:
        d["categorias"].pop(chave)
        _save(d)
        return True
    return False


def listar() -> dict:
    return _load()["categorias"]


def _gasto_categoria_mes(categoria: str, mes: date | None = None) -> float:
    """Soma o gasto realizado da categoria no mês (contas a pagar baixadas)."""
    if not mes:
        mes = date.today().replace(day=1)
    if mes.month == 12:
        from datetime import timedelta
        fim = mes.replace(year=mes.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        from datetime import timedelta
        fim = mes.replace(month=mes.month + 1, day=1) - timedelta(days=1)
    p = {"data_vencimento_de": str(mes), "data_vencimento_ate": str(fim)}
    pag = _buscar("contas-a-pagar/buscar", p)
    cat_l = categoria.lower().strip()
    total = 0.0
    for i in pag:
        nome_cat = ""
        rateio = i.get("rateio") or []
        if rateio:
            nome_cat = (rateio[0].get("categoria") or {}).get("nome", "") or ""
        if cat_l in nome_cat.lower():
            total += _valor_pago(i) or _valor(i)
    return total


def status_atual(mes: date | None = None) -> list[dict]:
    """Lista dicts {categoria, limite, gasto, pct}."""
    d = _load()
    out = []
    for cat, limite in d["categorias"].items():
        gasto = _gasto_categoria_mes(cat, mes)
        pct = (gasto / limite * 100) if limite else 0
        out.append({"categoria": cat, "limite": limite, "gasto": gasto, "pct": pct})
    return out


def checar_alertas() -> list[dict]:
    """Retorna alertas novos (não enviados ainda neste mês), marcando como enviados."""
    d = _load()
    chave_mes = date.today().strftime("%Y-%m")
    enviados = d["alertas_enviados"].setdefault(chave_mes, {})
    novos = []
    for s in status_atual():
        cat = s["categoria"]
        nivel = None
        if s["pct"] >= 100:
            nivel = "100"
        elif s["pct"] >= 80:
            nivel = "80"
        if nivel and enviados.get(cat) != nivel:
            enviados[cat] = nivel
            novos.append({**s, "nivel": nivel})
    if novos:
        _save(d)
    return novos

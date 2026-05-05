"""Geração de gráficos via Plotly + Kaleido. Retorna PNG bytes."""
import io
from datetime import date, timedelta
from collections import defaultdict
import plotly.graph_objects as go
from consulta_financeira import _buscar, _valor, _valor_pago, STATUS_RECEBIDO


def _png(fig) -> bytes:
    return fig.to_image(format="png", width=900, height=550, scale=2)


def _periodo_meses(n: int) -> list[date]:
    hoje = date.today().replace(day=1)
    meses = []
    for i in range(n - 1, -1, -1):
        m = hoje.month - i - 1
        ano = hoje.year + m // 12
        mes = m % 12 + 1
        meses.append(date(ano, mes, 1))
    return meses


def grafico_meses(n: int = 6) -> bytes:
    """Receita vs despesa realizada nos últimos n meses."""
    meses = _periodo_meses(n)
    rotulos, recs, pags = [], [], []
    for m in meses:
        if m.month == 12:
            fim = m.replace(year=m.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            fim = m.replace(month=m.month + 1, day=1) - timedelta(days=1)
        p = {"data_vencimento_de": str(m), "data_vencimento_ate": str(fim)}
        rec = _buscar("contas-a-receber/buscar", p)
        pag = _buscar("contas-a-pagar/buscar",   p)
        recs.append(sum(_valor_pago(i) for i in rec if i.get("status") in STATUS_RECEBIDO))
        pags.append(sum(_valor_pago(i) for i in pag if i.get("status") in STATUS_RECEBIDO))
        rotulos.append(m.strftime("%b/%y"))

    fig = go.Figure([
        go.Bar(name="Recebido", x=rotulos, y=recs, marker_color="#16a34a"),
        go.Bar(name="Pago",     x=rotulos, y=pags, marker_color="#dc2626"),
    ])
    fig.update_layout(
        title=f"Receita vs Despesa — últimos {n} meses",
        barmode="group", template="plotly_white",
        yaxis_title="R$",
    )
    return _png(fig)


def grafico_categorias(tipo: str = "PAGAR", mes: date | None = None) -> bytes:
    """Pizza de despesas (ou receitas) do mês por categoria."""
    if not mes:
        mes = date.today().replace(day=1)
    if mes.month == 12:
        fim = mes.replace(year=mes.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        fim = mes.replace(month=mes.month + 1, day=1) - timedelta(days=1)

    endpoint = "contas-a-pagar/buscar" if tipo == "PAGAR" else "contas-a-receber/buscar"
    p = {"data_vencimento_de": str(mes), "data_vencimento_ate": str(fim)}
    itens = _buscar(endpoint, p)

    # Monta lookup id_categoria → nome usando o catálogo
    try:
        from catalogo import categorias_despesa, categorias_receita
        cats = categorias_despesa() if tipo == "PAGAR" else categorias_receita()
        cat_map: dict[str, str] = {c["id"]: c.get("nome", "?") for c in cats if "id" in c}
    except Exception:
        cat_map = {}

    soma: dict[str, float] = defaultdict(float)
    for i in itens:
        rateio = i.get("rateio") or []
        if rateio:
            # Distribui o valor entre todas as categorias do rateio
            for r in rateio:
                id_cat = r.get("id_categoria")
                nome   = cat_map.get(id_cat, "(sem categoria)") if id_cat else "(sem categoria)"
                # Usa o valor do rateio se disponível, senão divide igualmente
                val    = r.get("valor") or (_valor(i) / len(rateio))
                soma[nome] += float(val)
        else:
            soma["(sem categoria)"] += _valor(i)

    if not soma or all(v == 0 for v in soma.values()):
        soma["(sem dados)"] = 0.01

    fig = go.Figure([go.Pie(labels=list(soma.keys()), values=list(soma.values()), hole=0.4)])
    titulo = "Despesas" if tipo == "PAGAR" else "Receitas"
    fig.update_layout(
        title=f"{titulo} por categoria — {mes.strftime('%b/%Y')}",
        template="plotly_white",
    )
    return _png(fig)


def grafico_fluxo_caixa(dias: int = 30) -> bytes:
    """Saldo projetado dia a dia, baseado em contas pendentes."""
    hoje = date.today()
    fim  = hoje + timedelta(days=dias)
    p = {"data_vencimento_de": str(hoje), "data_vencimento_ate": str(fim)}
    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)

    saldo: dict[str, float] = defaultdict(float)
    for i in rec:
        saldo[i.get("data_vencimento", "")] += _valor(i)
    for i in pag:
        saldo[i.get("data_vencimento", "")] -= _valor(i)

    chaves = sorted(k for k in saldo.keys() if k)
    acumulado, valores = 0, []
    for k in chaves:
        acumulado += saldo[k]
        valores.append(acumulado)

    fig = go.Figure([go.Scatter(x=chaves, y=valores, fill="tozeroy", line_color="#2563eb")])
    fig.update_layout(
        title=f"Fluxo de caixa projetado — próximos {dias} dias",
        template="plotly_white", yaxis_title="Saldo acumulado (R$)",
    )
    return _png(fig)

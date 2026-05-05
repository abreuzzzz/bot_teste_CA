"""Aging de recebíveis: agrupa parcelas por faixa de atraso."""
from datetime import date, timedelta
from consulta_financeira import _buscar, _valor

FAIXAS = [
    ("em_dia",   "✅ Em dia (vence no futuro)"),
    ("ate_30",   "🟡 Vence em até 30 dias"),
    ("d31_60",   "🟠 31 – 60 dias em atraso"),
    ("d61_90",   "🔴 61 – 90 dias em atraso"),
    ("acima_90", "⛔ Acima de 90 dias"),
]


def gerar_aging(tipo: str = "RECEBER") -> dict:
    """
    Retorna parcelas a receber (padrão) ou a pagar agrupadas por faixa.
    tipo = 'RECEBER' | 'PAGAR'
    """
    hoje  = date.today()
    endpoint = ("contas-a-receber/buscar" if tipo == "RECEBER"
                else "contas-a-pagar/buscar")

    # Busca tudo em aberto / atrasado
    p = {
        "data_vencimento_de":  "2020-01-01",
        "data_vencimento_ate": str(hoje + timedelta(days=90)),
        "status":              ["EM_ABERTO", "ATRASADO"],
    }
    itens = _buscar(endpoint, p)

    grupos: dict[str, list] = {k: [] for k, _ in FAIXAS}

    for i in itens:
        venc_str = i.get("data_vencimento", "")
        try:
            venc = date.fromisoformat(venc_str)
        except ValueError:
            continue
        delta = (hoje - venc).days   # positivo = atrasado

        if delta < 0:               # vence no futuro
            grupos["em_dia"].append(i)
        elif delta <= 30:
            grupos["ate_30"].append(i)
        elif delta <= 60:
            grupos["d31_60"].append(i)
        elif delta <= 90:
            grupos["d61_90"].append(i)
        else:
            grupos["acima_90"].append(i)

    resumo = {}
    total_geral = 0.0
    for chave, label in FAIXAS:
        lst   = grupos[chave]
        total = sum(_valor(i) for i in lst)
        total_geral += total
        resumo[chave] = {
            "label":  label,
            "qtd":    len(lst),
            "total":  round(total, 2),
            "itens":  lst[:5],   # primeiros 5 para detalhes
        }

    return {
        "tipo":         tipo,
        "data_base":    str(hoje),
        "faixas":       resumo,
        "total_geral":  round(total_geral, 2),
    }


def formatar_aging(a: dict) -> str:
    tipo_str = "Recebíveis" if a["tipo"] == "RECEBER" else "Pagáveis"
    linhas   = [f"📋 *Aging de {tipo_str}* — base {a['data_base']}\n"]
    for chave, _ in FAIXAS:
        f = a["faixas"][chave]
        if f["qtd"] == 0:
            continue
        pct = (f["total"] / a["total_geral"] * 100) if a["total_geral"] else 0
        linhas.append(
            f"{f['label']}\n"
            f"  {f['qtd']} parcela(s) — R$ {f['total']:,.2f}  ({pct:.1f}%)"
        )
    linhas.append(f"\n💰 *Total geral: R$ {a['total_geral']:,.2f}*")
    return "\n".join(linhas)

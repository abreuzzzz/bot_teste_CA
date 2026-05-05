"""DRE simplificado: Receitas e Despesas por categoria do mês."""
from datetime import date, timedelta
from consulta_financeira import _buscar, _valor, _valor_pago, STATUS_RECEBIDO


def gerar_dre(mes: date = None) -> dict:
    """
    Retorna DRE do mês: receitas e despesas agrupadas por categoria,
    ordenadas por valor decrescente.
    """
    if not mes:
        mes = date.today().replace(day=1)
    if mes.month == 12:
        fim = mes.replace(year=mes.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        fim = mes.replace(month=mes.month + 1, day=1) - timedelta(days=1)

    p = {"data_vencimento_de": str(mes), "data_vencimento_ate": str(fim)}
    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)

    def _agrupar(itens: list, usar_pago: bool = False) -> dict:
        grupos: dict[str, float] = {}
        for i in itens:
            # /buscar retorna categoria dentro de "rateio" ou objeto "categoria"
            nome_cat = None
            cat = i.get("categoria")
            if isinstance(cat, dict):
                nome_cat = cat.get("nome")
            if not nome_cat:
                rateio = i.get("rateio") or []
                if rateio and isinstance(rateio, list):
                    cat_r = rateio[0].get("categoria") or {}
                    nome_cat = cat_r.get("nome") if isinstance(cat_r, dict) else None
            if not nome_cat:
                nome_cat = "Sem categoria"
            v = _valor_pago(i) if (usar_pago and i.get("status") in STATUS_RECEBIDO) else _valor(i)
            grupos[nome_cat] = grupos.get(nome_cat, 0) + v
        return dict(sorted(grupos.items(), key=lambda x: -x[1]))

    receitas_total  = sum(_valor(i) for i in rec)
    despesas_total  = sum(_valor(i) for i in pag)
    recebido_total  = sum(_valor_pago(i) for i in rec if i.get("status") in STATUS_RECEBIDO)
    pago_total      = sum(_valor_pago(i) for i in pag if i.get("status") in STATUS_RECEBIDO)

    return {
        "periodo":          f"{mes.strftime('%m/%Y')}",
        "periodo_full":     f"{mes.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}",
        "receitas_cat":     _agrupar(rec),
        "despesas_cat":     _agrupar(pag),
        "receitas_total":   round(receitas_total, 2),
        "despesas_total":   round(despesas_total, 2),
        "recebido_total":   round(recebido_total, 2),
        "pago_total":       round(pago_total, 2),
        "resultado_bruto":  round(receitas_total - despesas_total, 2),
        "resultado_caixa":  round(recebido_total - pago_total, 2),
        "margem_pct":       round(((receitas_total - despesas_total) / receitas_total * 100)
                                  if receitas_total else 0, 1),
    }


def formatar_dre(d: dict) -> str:
    """Formata o DRE como texto Markdown para o Telegram."""
    linhas = [f"📊 *DRE — {d['periodo']}*\n"]

    # Receitas
    linhas.append("📥 *RECEITAS*")
    for cat, v in list(d["receitas_cat"].items())[:10]:
        linhas.append(f"  `{cat[:28]:<28}` R$ {v:>10,.2f}")
    linhas.append(f"  {'─'*40}")
    linhas.append(f"  *Total Receitas:* R$ {d['receitas_total']:>10,.2f}\n")

    # Despesas
    linhas.append("📤 *DESPESAS*")
    for cat, v in list(d["despesas_cat"].items())[:10]:
        linhas.append(f"  `{cat[:28]:<28}` R$ {v:>10,.2f}")
    linhas.append(f"  {'─'*40}")
    linhas.append(f"  *Total Despesas:* R$ {d['despesas_total']:>10,.2f}\n")

    # Resultado
    emoji = "✅" if d["resultado_bruto"] >= 0 else "🔴"
    linhas.append(f"{emoji} *RESULTADO: R$ {d['resultado_bruto']:,.2f}*  ({d['margem_pct']}%)\n")
    linhas.append(f"💰 Caixa realizado: R$ {d['resultado_caixa']:,.2f}")

    return "\n".join(linhas)

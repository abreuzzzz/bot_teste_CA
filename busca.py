"""Busca livre por descrição/contato em um período. Resume valor, qtd e lista."""
import re
from datetime import date, timedelta
from consulta_financeira import _buscar, _valor, _valor_pago

ANO_RX = re.compile(r"\b(20\d{2})\b")


def parse_periodo_livre(texto: str) -> tuple[date, date]:
    """Detecta ano (2020-2099) ou padrão últimos 12 meses."""
    hoje = date.today()
    m = ANO_RX.search(texto or "")
    if m:
        ano = int(m.group(1))
        return date(ano, 1, 1), date(ano, 12, 31)
    return hoje.replace(year=hoje.year - 1), hoje


def buscar(termo: str, ini: date | None = None, fim: date | None = None,
           tipo: str = "AMBOS") -> dict:
    """Retorna {qtd_pago, qtd_pendente, total_pago, total_pendente, itens}."""
    if not ini or not fim:
        ini, fim = parse_periodo_livre(termo)
    p = {"data_vencimento_de": str(ini), "data_vencimento_ate": str(fim)}
    fontes = []
    if tipo in ("RECEBER", "AMBOS"):
        fontes.append(("RECEBER", "contas-a-receber/buscar"))
    if tipo in ("PAGAR", "AMBOS"):
        fontes.append(("PAGAR", "contas-a-pagar/buscar"))

    termo_l = termo.lower()
    itens = []
    for t, ep in fontes:
        for i in _buscar(ep, p):
            desc = (i.get("descricao") or "").lower()
            contato = ""
            c = i.get("contato")
            if isinstance(c, dict):
                contato = (c.get("nome") or "").lower()
            if any(w in desc or w in contato for w in termo_l.split() if len(w) > 2):
                itens.append({"tipo": t, **i})

    qtd_pago = sum(1 for i in itens if i.get("status") in ("RECEBIDO", "PAGO", "RECEBIDO_PARCIAL", "PAGO_PARCIAL"))
    qtd_pend = len(itens) - qtd_pago
    total_pago = sum(_valor_pago(i) for i in itens
                     if i.get("status") in ("RECEBIDO", "PAGO", "RECEBIDO_PARCIAL", "PAGO_PARCIAL"))
    total_pend = sum(_valor(i) for i in itens
                     if i.get("status") not in ("RECEBIDO", "PAGO", "RECEBIDO_PARCIAL", "PAGO_PARCIAL"))

    return {
        "periodo":        f"{ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}",
        "qtd_pago":       qtd_pago,
        "qtd_pendente":   qtd_pend,
        "total_pago":     total_pago,
        "total_pendente": total_pend,
        "itens":          itens,
    }


def formatar_resumo(termo: str, r: dict, limite: int = 10) -> str:
    linhas = [
        f"🔍 *Busca:* _{termo}_",
        f"📅 Período: {r['periodo']}",
        "",
        f"✅ Pagos/Recebidos: {r['qtd_pago']} → R$ {r['total_pago']:.2f}",
        f"⏳ Pendentes:        {r['qtd_pendente']} → R$ {r['total_pendente']:.2f}",
    ]
    if r["itens"]:
        linhas.append("\n*Top resultados:*")
        for i in r["itens"][:limite]:
            emoji = "📥" if i["tipo"] == "RECEBER" else "📤"
            desc = (i.get("descricao", "?") or "?")[:35]
            v = _valor_pago(i) or _valor(i)
            linhas.append(f"  {emoji} {desc} — R$ {v:.2f} ({i.get('data_vencimento', '')})")
    else:
        linhas.append("\n_Nenhum lançamento encontrado._")
    return "\n".join(linhas)

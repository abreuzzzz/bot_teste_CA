"""Busca livre por descrição/contato em um período. Resume valor, qtd e lista."""
import re, requests
from datetime import date, timedelta
from consulta_financeira import _buscar, _valor, _valor_pago
from auth_contaazul import get_access_token

ANO_RX = re.compile(r"\b(20\d{2})\b")


def _resolver_cliente_ids(nome: str) -> list[str]:
    """Tenta resolver nome de cliente para lista de IDs via GET /v1/pessoas."""
    try:
        r = requests.get(
            "https://api-v2.contaazul.com/v1/pessoas",
            headers={"Authorization": f"Bearer {get_access_token()}"},
            params={"busca": nome, "pagina": 1, "tamanho_pagina": 10},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data  = r.json()
        itens = data.get("itens") or data.get("items") or []
        return [i["id"] for i in itens if "id" in i]
    except Exception as e:
        print(f"[BUSCA] Erro ao resolver cliente '{nome}': {e}")
        return []


def parse_periodo_livre(texto: str) -> tuple[date, date]:
    """Detecta ano (2020-2099) ou padrão últimos 12 meses."""
    hoje = date.today()
    m = ANO_RX.search(texto or "")
    if m:
        ano = int(m.group(1))
        return date(ano, 1, 1), date(ano, 12, 31)
    return hoje.replace(year=hoje.year - 1), hoje


def buscar(termo: str, ini: date | None = None, fim: date | None = None,
           tipo: str = "AMBOS", cliente: str | None = None) -> dict:
    """Retorna {qtd_pago, qtd_pendente, total_pago, total_pendente, itens}."""
    if not ini or not fim:
        ini, fim = parse_periodo_livre(termo)
    p = {"data_vencimento_de": str(ini), "data_vencimento_ate": str(fim)}

    # Filtro por cliente: resolve nome → IDs e envia para a API
    if cliente:
        ids = _resolver_cliente_ids(cliente)
        if ids:
            p["ids_clientes"] = ids

    fontes = []
    if tipo in ("RECEBER", "AMBOS"):
        fontes.append(("RECEBER", "contas-a-receber/buscar"))
    if tipo in ("PAGAR", "AMBOS"):
        fontes.append(("PAGAR", "contas-a-pagar/buscar"))

    termo_l = termo.lower()
    itens = []
    for t, ep in fontes:
        for i in _buscar(ep, p):
            desc    = (i.get("descricao") or "").lower()
            contato = ""
            c = i.get("contato")
            if isinstance(c, dict):
                contato = (c.get("nome") or "").lower()
            # Se já filtramos por IDs via API, inclui todos; caso contrário filtra por texto
            if "ids_clientes" in p or any(w in desc or w in contato
                                           for w in termo_l.split() if len(w) > 2):
                itens.append({"tipo": t, **i})

    _STATUS_PAGO = ("RECEBIDO", "QUITADO", "RECEBIDO_PARCIAL")
    qtd_pago = sum(1 for i in itens if i.get("status") in _STATUS_PAGO)
    qtd_pend = len(itens) - qtd_pago
    total_pago = sum(_valor_pago(i) for i in itens
                     if i.get("status") in _STATUS_PAGO)
    total_pend = sum(_valor(i) for i in itens
                     if i.get("status") not in _STATUS_PAGO)

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

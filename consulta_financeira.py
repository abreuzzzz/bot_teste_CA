import requests
from datetime import date, timedelta
from auth_contaazul import get_access_token

BASE = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"

STATUS_PENDENTE = ["EM_ABERTO", "ATRASADO"]
STATUS_RECEBIDO = ["RECEBIDO", "RECEBIDO_PARCIAL"]


def _h() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def _valor(item: dict) -> float:
    """
    A API retorna o valor em campos diferentes dependendo do endpoint.
    Tenta: valor_composicao.valor_bruto → valor_bruto → valor → 0
    """
    vc = item.get("valor_composicao") or {}
    return (
        vc.get("valor_bruto")
        or item.get("valor_bruto")
        or item.get("valor")
        or 0.0
    )


def _buscar(endpoint: str, params: dict) -> list:
    itens, pagina = [], 1
    while True:
        r = requests.get(
            f"{BASE}/{endpoint}",
            headers=_h(),
            params={"pagina": pagina, "tamanho_pagina": 200, **params},
            timeout=15,
        )
        print(f"[CFQ] GET {BASE}/{endpoint} → HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"[CFQ] Erro: {r.text[:300]}")
            break
        data  = r.json()
        batch = data.get("itens", [])
        itens += batch
        if len(itens) >= data.get("itens_totais", len(itens)):
            break
        pagina += 1
    return itens


def resumo_mes(mes: date = None) -> dict:
    if not mes:
        mes = date.today().replace(day=1)

    if mes.month == 12:
        fim = mes.replace(year=mes.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        fim = mes.replace(month=mes.month + 1, day=1) - timedelta(days=1)

    p = {
        "data_vencimento_de":  str(mes),
        "data_vencimento_ate": str(fim),
    }

    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)

    total_rec = sum(_valor(i) for i in rec)
    total_pag = sum(_valor(i) for i in pag)
    recebido  = sum(_valor(i) for i in rec if i.get("status") in STATUS_RECEBIDO)
    pago      = sum(_valor(i) for i in pag if i.get("status") in STATUS_RECEBIDO)

    hoje = str(date.today())
    atrasados_rec = [i for i in rec if i.get("status") in STATUS_PENDENTE and i.get("data_vencimento", "") < hoje]
    atrasados_pag = [i for i in pag if i.get("status") in STATUS_PENDENTE and i.get("data_vencimento", "") < hoje]

    return {
        "periodo":           f"{mes.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}",
        "total_receber":     total_rec,
        "total_pagar":       total_pag,
        "recebido":          recebido,
        "pago":              pago,
        "resultado":         recebido - pago,
        "saldo_projetado":   total_rec - total_pag,
        "atrasados_receber": len(atrasados_rec),
        "atrasados_pagar":   len(atrasados_pag),
        "contas_receber":    rec,
        "contas_pagar":      pag,
    }


def pendentes(tipo: str = "AMBOS", dias: int = 30) -> list:
    hoje = date.today()
    fim  = hoje + timedelta(days=dias)
    p    = {
        "data_vencimento_de":  str(hoje),
        "data_vencimento_ate": str(fim),
        "status":              STATUS_PENDENTE,
    }
    result = []
    if tipo in ("RECEBER", "AMBOS"):
        result += [{"tipo": "RECEBER", **i} for i in _buscar("contas-a-receber/buscar", p)]
    if tipo in ("PAGAR", "AMBOS"):
        result += [{"tipo": "PAGAR",   **i} for i in _buscar("contas-a-pagar/buscar",  p)]
    return sorted(result, key=lambda x: x.get("data_vencimento", ""))


def atrasados(tipo: str = "AMBOS") -> list:
    ontem = date.today() - timedelta(days=1)
    p = {
        "data_vencimento_de":  "2020-01-01",
        "data_vencimento_ate": str(ontem),
        "status":              ["ATRASADO"],
    }
    result = []
    if tipo in ("RECEBER", "AMBOS"):
        result += [{"tipo": "RECEBER", **i} for i in _buscar("contas-a-receber/buscar", p)]
    if tipo in ("PAGAR", "AMBOS"):
        result += [{"tipo": "PAGAR",   **i} for i in _buscar("contas-a-pagar/buscar",  p)]
    return sorted(result, key=lambda x: x.get("data_vencimento", ""))

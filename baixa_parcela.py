import requests
from datetime import date
from auth_contaazul import get_access_token

BASE = "https://api-v2.contaazul.com/v1/financeiro"


def _h():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }


def dar_baixa(parcela_id: str, tipo: str, data_pagamento: str = None) -> bool:
    data_pgto = data_pagamento or str(date.today())
    endpoint  = "contas-a-receber" if tipo == "RECEBER" else "contas-a-pagar"
    url       = f"{BASE}/{endpoint}/{parcela_id}/baixa"
    r         = requests.post(url, headers=_h(), json={"data_pagamento": data_pgto}, timeout=15)
    return r.status_code in (200, 201, 204)


def buscar_por_descricao(texto: str, tipo: str) -> list:
    from consulta_financeira import _buscar
    p     = {"data_vencimento_de": "2024-01-01", "data_vencimento_ate": "2027-12-31", "status": "PENDENTE"}
    endpoint = "contas-a-receber/buscar" if tipo == "RECEBER" else "contas-a-pagar/buscar"
    itens = _buscar(endpoint, p)
    texto_l = texto.lower()
    return [i for i in itens if texto_l in i.get("descricao", "").lower()]

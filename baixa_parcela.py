import requests
from datetime import date
from auth_contaazul import get_access_token

BASE_PARCELAS = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/parcelas"


def _h() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type":  "application/json",
    }


def dar_baixa(parcela_id: str, tipo: str, data_pagamento: str = None) -> bool:
    """
    Dá baixa em uma parcela pelo seu ID.
    Endpoint: POST /v1/financeiro/eventos-financeiros/parcelas/{id}/baixas
    """
    data_pgto = data_pagamento or str(date.today())
    url = f"{BASE_PARCELAS}/{parcela_id}/baixas"

    body = {
        "data_pagamento": data_pgto,
        # metodo_pagamento é opcional — omitido para usar o padrão da conta
    }

    r = requests.post(url, headers=_h(), json=body, timeout=15)
    print(f"[BAIXA] POST {url} → HTTP {r.status_code}")

    if r.status_code not in (200, 201, 202, 204):
        print(f"[BAIXA] Erro: {r.text[:300]}")
        return False
    return True


def buscar_por_descricao(texto: str, tipo: str) -> list:
    """
    Busca parcelas pendentes por descrição.
    Retorna lista de parcelas que contenham o texto na descrição.
    """
    from consulta_financeira import _buscar

    endpoint = "contas-a-receber/buscar" if tipo == "RECEBER" else "contas-a-pagar/buscar"
    p = {
        "data_vencimento_de":  "2024-01-01",
        "data_vencimento_ate": "2027-12-31",
        "status":              ["EM_ABERTO", "ATRASADO"],  # status corretos da API v2
    }

    itens   = _buscar(endpoint, p)
    texto_l = texto.lower()
    return [i for i in itens if texto_l in i.get("descricao", "").lower()]

import requests
from datetime import date, timedelta
from auth_contaazul import get_access_token

BASE_PARCELAS = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/parcelas"


def _h() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type":  "application/json",
    }


METODOS_PAGAMENTO = [
    ("PIX",                    "PIX"),
    ("DINHEIRO",               "Dinheiro"),
    ("BOLETO_BANCARIO",        "Boleto"),
    ("CARTAO_CREDITO",         "Cartão Crédito"),
    ("CARTAO_DEBITO",          "Cartão Débito"),
    ("TRANSFERENCIA_BANCARIA", "Transferência"),
    ("DEPOSITO_BANCARIO",      "Depósito"),
    ("OUTRO",                  "Outro"),
]


def dar_baixa(parcela_id: str, tipo: str, data_pagamento: str = None,
              metodo_pagamento: str = None) -> bool:
    """
    Dá baixa em uma parcela pelo seu ID.
    Endpoint: POST /v1/financeiro/eventos-financeiros/parcelas/{id}/baixas
    """
    data_pgto = data_pagamento or str(date.today())
    url = f"{BASE_PARCELAS}/{parcela_id}/baixas"

    body: dict = {"data_pagamento": data_pgto}
    if metodo_pagamento:
        body["metodo_pagamento"] = metodo_pagamento

    r = requests.post(url, headers=_h(), json=body, timeout=15)
    print(f"[BAIXA] POST {url} → HTTP {r.status_code}")

    if r.status_code not in (200, 201, 202, 204):
        print(f"[BAIXA] Erro: {r.text[:300]}")
        return False
    return True


def dar_baixa_parcial(parcela_id: str, tipo: str,
                      valor_pago: float,
                      data_pagamento: str = None,
                      metodo_pagamento: str = None) -> bool:
    """
    Registra recebimento/pagamento parcial.
    Usa o mesmo endpoint de baixa com campo 'valor_pago' menor que o total.
    """
    data_pgto = data_pagamento or str(date.today())
    url  = f"{BASE_PARCELAS}/{parcela_id}/baixas"
    body: dict = {
        "data_pagamento": data_pgto,
        "valor_pago":     valor_pago,
    }
    if metodo_pagamento:
        body["metodo_pagamento"] = metodo_pagamento

    r = requests.post(url, headers=_h(), json=body, timeout=15)
    print(f"[BAIXA PARCIAL] POST {url} → HTTP {r.status_code}")
    if r.status_code not in (200, 201, 202, 204):
        print(f"[BAIXA PARCIAL] Erro: {r.text[:300]}")
        return False
    return True


def get_parcela(parcela_id: str) -> dict | None:
    """Retorna os detalhes completos de uma parcela pelo ID."""
    r = requests.get(f"{BASE_PARCELAS}/{parcela_id}", headers=_h(), timeout=10)
    if r.status_code != 200:
        print(f"[BAIXA] get_parcela erro {r.status_code}: {r.text[:200]}")
        return None
    return r.json()


def patch_parcela(parcela_id: str, campos: dict) -> bool:
    """Atualiza parcialmente uma parcela. Requer campo 'versao' no payload."""
    r = requests.patch(
        f"{BASE_PARCELAS}/{parcela_id}",
        headers=_h(), json=campos, timeout=15,
    )
    print(f"[PATCH] PATCH {BASE_PARCELAS}/{parcela_id} → HTTP {r.status_code}")
    if r.status_code not in (200, 201, 204):
        print(f"[PATCH] Erro: {r.text[:300]}")
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
        "data_vencimento_ate": str(date.today() + timedelta(days=730)),
        "status":              ["EM_ABERTO", "ATRASADO"],  # status corretos da API v2
    }

    itens   = _buscar(endpoint, p)
    texto_l = texto.lower()
    return [i for i in itens if texto_l in i.get("descricao", "").lower()]

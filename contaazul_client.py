import requests, time
from auth_contaazul import get_access_token
from catalogo import categorias_receita, categorias_despesa, contas_financeiras, centros_custo

BASE = "https://api-v2.contaazul.com/v1/financeiro"
RETRY_MAX = 3


def _h():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }


def _post(url: str, body: dict) -> dict:
    for tentativa in range(1, RETRY_MAX + 1):
        r = requests.post(url, headers=_h(), json=body, timeout=20)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 500 and tentativa < RETRY_MAX:
            print(f"[CA] Retry {tentativa} — status 500")
            time.sleep(2 ** tentativa)
            continue
        r.raise_for_status()
    raise Exception("Máximo de tentativas atingido")


def _sanitizar(texto: str) -> str:
    return texto[:255] if texto else "Lançamento automático"


def _rateio(categoria_id: str, valor: float, centro_id: str | None) -> list:
    item = {"categoria": categoria_id, "valor": valor}
    if centro_id:
        item["centro_custo"] = centro_id
    return [item]


def _verificar_duplicata(titulo: str, valor: float, vencimento: str, tipo: str) -> bool:
    endpoint = "contas-a-receber/buscar" if tipo == "RECEBER" else "contas-a-pagar/buscar"
    r = requests.get(
        f"{BASE}/{endpoint}",
        headers=_h(),
        params={
            "pagina": 1, "tamanho_pagina": 10,
            "data_vencimento_de": vencimento,
            "data_vencimento_ate": vencimento,
        },
        timeout=15,
    )
    if r.status_code != 200:
        return False
    itens = r.json().get("itens", [])
    for i in itens:
        if abs(i.get("valor", 0) - valor) < 0.01 and titulo.lower() in i.get("descricao", "").lower():
            return True
    return False


def criar_lancamento(dados: dict) -> dict:
    """
    dados = resultado de fluxo_lancamento após confirmação.
    Retorna {"ok": True, "ids": [...]} ou {"ok": False, "erro": str}
    """
    tipo      = dados["tipo"]
    titulo    = _sanitizar(dados["titulo"])
    valor     = float(dados["valor"])
    parcelas  = int(dados.get("parcelas", 1))
    venc      = dados["vencimento"]

    # IDs resolvidos pelo fluxo de seleção (ou fallback para primeiro da lista)
    conta_id    = dados.get("conta_id")    or (contas_financeiras() or [{}])[0].get("id")
    cat_id      = dados.get("categoria_id") or _cat_padrao(tipo)
    centro_id   = dados.get("centro_id")

    if not conta_id or not cat_id:
        return {"ok": False, "erro": "Conta ou categoria não encontrada no Conta Azul."}

    # Anti-duplicata
    if _verificar_duplicata(titulo, valor, venc, tipo):
        return {"ok": False, "erro": "DUPLICATA", "mensagem": f"Já existe um lançamento similar de R$ {valor:.2f} em {venc}."}

    valor_parcela = round(valor / parcelas, 2)
    from datetime import date, timedelta
    venc_dt = date.fromisoformat(venc)

    parcelas_body = []
    for n in range(parcelas):
        data_p = venc_dt if n == 0 else (date(venc_dt.year + (venc_dt.month + n - 1) // 12,
                                              (venc_dt.month + n - 1) % 12 + 1, venc_dt.day))
        parcelas_body.append({
            "descricao": _sanitizar(f"{titulo} ({n+1}/{parcelas})"),
            "data_vencimento": str(data_p),
            "nota": "Lançamento automático",
            "conta_financeira": conta_id,
            "detalhe_valor": {
                "valor_bruto":   valor_parcela,
                "valor_liquido": valor_parcela,
            },
        })

    body = {
        "data_competencia": venc,
        "valor":            valor,
        "descricao":        titulo,
        "observacao":       "Lançamento automático via bot",
        "conta_financeira": conta_id,
        "rateio":           _rateio(cat_id, valor, centro_id),
        "condicao_pagamento": {"parcelas": parcelas_body},
    }

    endpoint = "contas-a-receber" if tipo == "RECEBER" else "contas-a-pagar"
    resultado = _post(f"{BASE}/{endpoint}", body)
    return {"ok": True, "id": resultado.get("id"), "tipo": tipo}


def _cat_padrao(tipo: str) -> str | None:
    lista = categorias_receita() if tipo == "RECEBER" else categorias_despesa()
    return lista[0]["id"] if lista else None

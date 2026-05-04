import requests, time
from datetime import date
from auth_contaazul import get_access_token
from catalogo import categorias_receita, categorias_despesa, contas_financeiras

BASE      = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
RETRY_MAX = 3


def _h() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type":  "application/json",
    }


def _post(url: str, body: dict) -> dict:
    for tentativa in range(1, RETRY_MAX + 1):
        r = requests.post(url, headers=_h(), json=body, timeout=20)
        print(f"[CA] POST {url} → HTTP {r.status_code}")

        # 202 = criado com sucesso (padrão da API Conta Azul v2)
        if r.status_code in (200, 201, 202):
            return r.json()

        if r.status_code == 500 and tentativa < RETRY_MAX:
            print(f"[CA] Retry {tentativa} — status 500")
            time.sleep(2 ** tentativa)
            continue

        print(f"[CA] Erro {r.status_code}: {r.text[:300]}")
        r.raise_for_status()

    raise Exception("Máximo de tentativas atingido")


def _sanitizar(texto: str) -> str:
    return texto[:255] if texto else "Lançamento automático"


def _rateio(categoria_id: str, valor: float, centro_id: str | None) -> list:
    """Monta o rateio conforme documentação da API v2."""
    item = {"id_categoria": categoria_id, "valor": valor}
    if centro_id:
        item["rateio_centro_custo"] = [{"id_centro_custo": centro_id, "valor": valor}]
    return [item]


def _verificar_duplicata(titulo: str, valor: float, vencimento: str, tipo: str) -> bool:
    endpoint = "contas-a-receber/buscar" if tipo == "RECEBER" else "contas-a-pagar/buscar"
    try:
        r = requests.get(
            f"{BASE}/{endpoint}",
            headers=_h(),
            params={
                "pagina":              1,
                "tamanho_pagina":      10,
                "data_vencimento_de":  vencimento,
                "data_vencimento_ate": vencimento,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return False
        itens = r.json().get("itens", [])
        for i in itens:
            mesmo_valor = abs(i.get("valor", 0) - valor) < 0.01
            mesmo_titulo = titulo.lower() in i.get("descricao", "").lower()
            if mesmo_valor and mesmo_titulo:
                return True
    except Exception as e:
        print(f"[CA] Erro ao verificar duplicata: {e}")
    return False


def criar_lancamento(dados: dict) -> dict:
    """
    dados = resultado do fluxo_lancamento após confirmação.
    Retorna {"ok": True, "id": protocolId} ou {"ok": False, "erro": str}
    """
    tipo     = dados["tipo"]
    titulo   = _sanitizar(dados["titulo"])
    valor    = float(dados["valor"])
    parcelas = int(dados.get("parcelas", 1))
    venc     = dados["vencimento"]

    # IDs resolvidos pelo fluxo de seleção
    conta_id  = dados.get("conta_id")    or (contas_financeiras() or [{}])[0].get("id")
    cat_id    = dados.get("categoria_id") or _cat_padrao(tipo)
    centro_id = dados.get("centro_id")

    if not conta_id:
        return {"ok": False, "erro": "Conta financeira não encontrada no Conta Azul."}
    if not cat_id:
        return {"ok": False, "erro": "Categoria não encontrada no Conta Azul."}

    # Anti-duplicata
    if _verificar_duplicata(titulo, valor, venc, tipo):
        return {
            "ok":       False,
            "erro":     "DUPLICATA",
            "mensagem": f"Já existe um lançamento similar de R$ {valor:.2f} em {venc}.",
        }

    # Monta parcelas com vencimentos mensais
    valor_parcela = round(valor / parcelas, 2)
    venc_dt       = date.fromisoformat(venc)
    parcelas_body = []

    for n in range(parcelas):
        mes_offset = venc_dt.month + n - 1
        data_p = date(
            venc_dt.year + mes_offset // 12,
            mes_offset % 12 + 1,
            venc_dt.day,
        )
        parcelas_body.append({
            "descricao":       _sanitizar(f"{titulo} ({n + 1}/{parcelas})"),
            "data_vencimento": str(data_p),
            "nota":            "Lançamento automático via bot",
            "conta_financeira": conta_id,
            "detalhe_valor": {
                "valor_bruto":   valor_parcela,
                "valor_liquido": valor_parcela,
            },
        })

    body = {
        "data_competencia":   venc,
        "valor":              valor,
        "descricao":          titulo,
        "observacao":         "Lançamento automático via bot",
        "conta_financeira":   conta_id,
        "rateio":             _rateio(cat_id, valor, centro_id),
        "condicao_pagamento": {"parcelas": parcelas_body},
    }

    # Contato é required na API — inclui se disponível
    contato_id = dados.get("contato_id")
    if contato_id:
        body["contato"] = contato_id

    endpoint  = "contas-a-receber" if tipo == "RECEBER" else "contas-a-pagar"
    resultado = _post(f"{BASE}/{endpoint}", body)

    # API retorna protocolId + status (não um id direto)
    return {
        "ok":   True,
        "id":   resultado.get("protocolId"),
        "tipo": tipo,
    }


def _cat_padrao(tipo: str) -> str | None:
    lista = categorias_receita() if tipo == "RECEBER" else categorias_despesa()
    return lista[0]["id"] if lista else None

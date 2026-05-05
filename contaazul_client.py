import requests, time
from datetime import date
from calendar import monthrange
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
        print(f"[CA] Payload enviado: {str(body)[:1000]}")

        if r.status_code in (200, 201, 202):
            try:
                data = r.json()
            except Exception:
                data = {}
            print(f"[CA] Response: {str(data)[:500]}")
            loc = r.headers.get("Location") or r.headers.get("location")
            if loc and isinstance(data, dict):
                data.setdefault("_location", loc)
            return data if isinstance(data, dict) else {"_raw": data}

        if r.status_code == 500 and tentativa < RETRY_MAX:
            print(f"[CA] Retry {tentativa} — status 500")
            time.sleep(2 ** tentativa)
            continue

        print(f"[CA] Erro {r.status_code}: {r.text[:2000]}")
        r.raise_for_status()

    raise Exception("Máximo de tentativas atingido")


def _extrair_id(resp: dict) -> str | None:
    if not isinstance(resp, dict):
        return None
    for k in ("id", "protocolId", "protocol_id", "protocolo", "uuid", "identifier", "_id"):
        v = resp.get(k)
        if v:
            return str(v)
    loc = resp.get("_location")
    if loc:
        return loc.rstrip("/").rsplit("/", 1)[-1]
    for k in ("data", "resultado", "resposta"):
        sub = resp.get(k)
        if isinstance(sub, dict):
            r = _extrair_id(sub)
            if r:
                return r
    return None


def _sanitizar(texto: str) -> str:
    return texto[:255] if texto else "Lançamento automático"


def _rateio(categoria_id: str, valor: float, centro_id: str | None) -> list:
    item = {"id_categoria": categoria_id, "valor": valor}
    if centro_id:
        item["rateio_centro_custo"] = [{"id_centro_custo": centro_id, "valor": valor}]
    return [item]


def _add_meses(d: date, n: int) -> date:
    total = d.month - 1 + n
    ano   = d.year + total // 12
    mes   = total % 12 + 1
    ultimo_dia = monthrange(ano, mes)[1]
    return date(ano, mes, min(d.day, ultimo_dia))


def _montar_parcelas(titulo: str, valor: float, parcelas: int, venc: str,
                     conta_id: str, observacao: str = "Lançamento automático via bot") -> list:
    valor_parcela = round(valor / parcelas, 2)
    venc_dt       = date.fromisoformat(venc)
    body = []
    for n in range(parcelas):
        data_p = _add_meses(venc_dt, n)
        body.append({
            "descricao":        _sanitizar(f"{titulo} ({n + 1}/{parcelas})"),
            "data_vencimento":  str(data_p),
            "nota":             observacao,                    # ← required pela API
            "conta_financeira": conta_id,                     # ← required pela API (por parcela)
            "detalhe_valor": {
                "valor_bruto": valor_parcela,
            },
        })
    return body


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
            mesmo_valor  = abs(i.get("valor", 0) - valor) < 0.01
            mesmo_titulo = titulo.lower() in i.get("descricao", "").lower()
            if mesmo_valor and mesmo_titulo:
                return True
    except Exception as e:
        print(f"[CA] Erro ao verificar duplicata: {e}")
    return False


def criar_lancamento(dados: dict, forcar: bool = False) -> dict:
    tipo      = dados["tipo"]
    titulo    = _sanitizar(dados["titulo"])
    valor     = float(dados["valor"])
    parcelas  = int(dados.get("parcelas", 1))
    venc      = dados["vencimento"]

    conta_id   = dados.get("conta_id")     or (contas_financeiras() or [{}])[0].get("id")
    cat_id     = dados.get("categoria_id") or _cat_padrao(tipo)
    centro_id  = dados.get("centro_id")
    contato_id = dados.get("contato_id")   or _contato_padrao()   # ← obrigatório

    if not conta_id:
        return {"ok": False, "erro": "Conta financeira não encontrada no Conta Azul."}
    if not cat_id:
        return {"ok": False, "erro": "Categoria não encontrada no Conta Azul."}
    if not contato_id:
        return {"ok": False, "erro": "Contato (negociador) não encontrado. Cadastre um contato no Conta Azul."}

    if not forcar and _verificar_duplicata(titulo, valor, venc, tipo):
        return {
            "ok":       False,
            "erro":     "DUPLICATA",
            "mensagem": f"Já existe um lançamento similar de R$ {valor:.2f} em {venc}.",
        }

    observacao = "Lançamento forçado via bot" if forcar else "Lançamento automático via bot"

    body = {
        "data_competencia":   venc,
        "valor":              valor,
        "descricao":          titulo,
        "observacao":         observacao,
        "contato":            contato_id,                      # ← required pela API
        "conta_financeira":   conta_id,
        "rateio":             _rateio(cat_id, valor, centro_id),
        "condicao_pagamento": {
            "parcelas": _montar_parcelas(titulo, valor, parcelas, venc, conta_id, observacao),
        },
    }

    endpoint  = "contas-a-receber" if tipo == "RECEBER" else "contas-a-pagar"
    resultado = _post(f"{BASE}/{endpoint}", body)

    return {
        "ok":   True,
        "id":   _extrair_id(resultado),
        "tipo": tipo,
    }


def _cat_padrao(tipo: str) -> str | None:
    lista = categorias_receita() if tipo == "RECEBER" else categorias_despesa()
    return lista[0]["id"] if lista else None


def _contato_padrao() -> str | None:
    """Busca o primeiro contato ativo na API do Conta Azul."""
    try:
        r = requests.get(
            "https://api-v2.contaazul.com/v1/pessoas",
            headers=_h(),
            params={"pagina": 1, "tamanho_pagina": 1},
            timeout=10,
        )
        if r.status_code == 200:
            itens = r.json().get("itens", [])
            if itens:
                return itens[0].get("id")
    except Exception as e:
        print(f"[CA] Erro ao buscar contato padrão: {e}")
    return None

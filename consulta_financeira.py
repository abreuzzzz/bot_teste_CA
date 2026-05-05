import requests
from datetime import date, timedelta
from auth_contaazul import get_access_token

BASE = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"

# A API retorna "PENDENTE" (== EM_ABERTO) e "QUITADO" (== RECEBIDO)
# em alguns endpoints; incluímos ambas as formas para compatibilidade.
STATUS_PENDENTE       = ["EM_ABERTO", "PENDENTE", "ATRASADO"]  # para comparar response
STATUS_PENDENTE_FILTRO = ["EM_ABERTO", "ATRASADO"]              # para enviar como filtro na API
STATUS_RECEBIDO       = ["RECEBIDO", "QUITADO", "RECEBIDO_PARCIAL"]


def _h() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def _valor(item: dict) -> float:
    """
    Hierarquia de campos conforme documentação API v2:
    1. valor_composicao.valor_bruto  (campo principal das parcelas)
    2. valor_bruto                   (campo raiz)
    3. valor_total_liquido           (campo raiz — retornado pelo /buscar)
    4. nao_pago                      (valor pendente da parcela)
    5. valor                         (fallback legado)
    """
    vc = item.get("valor_composicao") or {}
    candidates = [
        vc.get("valor_bruto"),
        item.get("valor_bruto"),
        item.get("valor_total_liquido"),
        item.get("nao_pago"),
        item.get("valor"),
    ]
    for v in candidates:
        if v is not None and v != 0:
            return float(v)
    return 0.0


def _valor_pago(item: dict) -> float:
    """
    Valor efetivamente pago/recebido conforme documentação API v2:
    1. valor_pago                    (campo direto da parcela)
    2. valor_composicao.valor_liquido (valor líquido após descontos/taxas)
    3. valor_composicao.valor_bruto  (fallback bruto)
    """
    vc = item.get("valor_composicao") or {}
    candidates = [
        item.get("valor_pago"),
        vc.get("valor_liquido"),
        vc.get("valor_bruto"),
    ]
    for v in candidates:
        if v is not None and v != 0:
            return float(v)
    return 0.0


import time as _time_mod


def _get_com_retry(url, headers, params, timeout=15, max_tentativas=3):
    """GET com tratamento de rate-limit (429) e retry."""
    for tentativa in range(1, max_tentativas + 1):
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        if r.status_code == 429 and tentativa < max_tentativas:
            espera = 35
            try:
                espera = int(r.headers.get("Retry-After", 35)) + 2
            except Exception:
                pass
            print(f"[CFQ] Rate limit (429). Aguardando {espera}s (tentativa {tentativa}/{max_tentativas})...")
            _time_mod.sleep(espera)
            continue
        return r
    return r


def _buscar(endpoint: str, params: dict) -> list:
    itens, pagina = [], 1
    while True:
        r = _get_com_retry(
            f"{BASE}/{endpoint}",
            headers=_h(),
            params={"pagina": pagina, "tamanho_pagina": 200, **params},
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

    # Usa _valor_pago para itens já quitados (valor efetivamente movimentado)
    recebido = sum(_valor_pago(i) for i in rec if i.get("status") in STATUS_RECEBIDO)
    pago     = sum(_valor_pago(i) for i in pag if i.get("status") in STATUS_RECEBIDO)

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
        "status":              STATUS_PENDENTE_FILTRO,
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


# ─── Saldo de contas ──────────────────────────────────────────────────────────

BASE_CONTA = "https://api-v2.contaazul.com/v1/conta-financeira"


def saldo_conta(conta_id: str) -> float | None:
    """Retorna o saldo atual de uma conta financeira específica."""
    r = _get_com_retry(
        f"{BASE_CONTA}/{conta_id}/saldo-atual",
        headers=_h(),
        params={},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"[CFQ] Saldo erro {r.status_code}: conta {conta_id}")
        return None
    return r.json().get("saldo_atual")


def saldo_todas_contas() -> list[dict]:
    """Retorna lista de contas ativas com saldo atual."""
    from catalogo import contas_financeiras
    contas = contas_financeiras()
    resultado = []
    for c in contas:
        saldo = saldo_conta(c["id"])
        resultado.append({
            "id":    c["id"],
            "nome":  c.get("nome", "?"),
            "tipo":  c.get("tipo", ""),
            "saldo": saldo,
        })
    return resultado


# ─── Transferências entre contas ─────────────────────────────────────────────

BASE_TRANSF = "https://api-v2.contaazul.com/v1/financeiro/transferencias"


def transferencias(ini: date = None, fim: date = None,
                   ids_contas: list[str] = None) -> list[dict]:
    """Consulta transferências entre contas no período."""
    hoje = date.today()
    ini  = ini or hoje.replace(day=1)
    fim  = fim or hoje
    params = {
        "pagina":         1,
        "tamanho_pagina": 200,
        "data_inicio":    str(ini),
        "data_fim":       str(fim),
    }
    if ids_contas:
        params["ids_conta_financeira"] = ids_contas
    r = _get_com_retry(BASE_TRANSF, headers=_h(), params=params, timeout=15)
    if r.status_code != 200:
        print(f"[CFQ] Transferências erro {r.status_code}: {r.text[:200]}")
        return []
    return r.json().get("itens", [])


# ─── Feature 2: Projeção de caixa ────────────────────────────────────────────

def projecao_caixa(dias: int = 15) -> dict:
    """
    Projeta o saldo para os próximos `dias` dias.
    Retorna: saldo_atual, a_receber, a_pagar, saldo_projetado, data_alerta, dias_ate_negativo
    """
    hoje = date.today()
    fim  = hoje + timedelta(days=dias)

    p = {
        "data_vencimento_de":  str(hoje),
        "data_vencimento_ate": str(fim),
        "status":              STATUS_PENDENTE_FILTRO,
    }
    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)

    a_receber = sum(_valor(i) for i in rec)
    a_pagar   = sum(_valor(i) for i in pag)

    # Saldo atual das contas
    try:
        contas       = saldo_todas_contas()
        saldo_atual  = sum(c.get("saldo") or 0 for c in contas)
    except Exception:
        saldo_atual  = 0.0

    # Simula dia a dia até encontrar primeiro dia negativo
    saldo_sim       = saldo_atual
    data_alerta     = None
    dias_ate_negativo = None

    # Agrupa saídas por data
    saidas_por_dia: dict[str, float] = {}
    entradas_por_dia: dict[str, float] = {}
    for i in pag:
        d = i.get("data_vencimento", "")
        saidas_por_dia[d] = saidas_por_dia.get(d, 0) + _valor(i)
    for i in rec:
        d = i.get("data_vencimento", "")
        entradas_por_dia[d] = entradas_por_dia.get(d, 0) + _valor(i)

    for delta in range(dias + 1):
        d_str = str(hoje + timedelta(days=delta))
        saldo_sim += entradas_por_dia.get(d_str, 0)
        saldo_sim -= saidas_por_dia.get(d_str, 0)
        if saldo_sim < 0 and data_alerta is None:
            data_alerta       = d_str
            dias_ate_negativo = delta

    return {
        "saldo_atual":        round(saldo_atual, 2),
        "a_receber":          round(a_receber, 2),
        "a_pagar":            round(a_pagar, 2),
        "saldo_projetado":    round(saldo_atual + a_receber - a_pagar, 2),
        "data_alerta":        data_alerta,
        "dias_ate_negativo":  dias_ate_negativo,
        "dias_simulados":     dias,
    }


# ─── Feature 3: Saldo por cliente ────────────────────────────────────────────

def saldo_cliente(nome: str) -> dict:
    """
    Retorna quanto um cliente deve / quanto a empresa deve a ele.
    Pesquisa em contas-a-receber e contas-a-pagar filtrando pelo nome.
    """
    import requests as _req
    from auth_contaazul import get_access_token

    # Resolve IDs do cliente
    try:
        r = _req.get(
            "https://api-v2.contaazul.com/v1/pessoas",
            headers={"Authorization": f"Bearer {get_access_token()}"},
            params={"busca": nome, "pagina": 1, "tamanho_pagina": 10},
            timeout=10,
        )
        pessoas = r.json().get("itens", []) if r.status_code == 200 else []
    except Exception:
        pessoas = []

    ids = [p["id"] for p in pessoas if "id" in p]

    hoje  = date.today()
    p_rec = {"data_vencimento_de": "2020-01-01", "data_vencimento_ate": str(hoje + timedelta(days=365)),
             "status": STATUS_PENDENTE}
    p_pag = dict(p_rec)
    if ids:
        p_rec["ids_clientes"] = ids
        p_pag["ids_clientes"] = ids

    rec = _buscar("contas-a-receber/buscar", p_rec)
    pag = _buscar("contas-a-pagar/buscar",   p_pag)

    # Filtra por nome se IDs não foram resolvidos
    if not ids:
        nome_lower = nome.lower()
        rec = [i for i in rec if nome_lower in (i.get("descricao") or "").lower()
               or nome_lower in (i.get("nome_cliente") or "").lower()]
        pag = [i for i in pag if nome_lower in (i.get("descricao") or "").lower()
               or nome_lower in (i.get("nome_fornecedor") or "").lower()]

    total_rec  = sum(_valor(i) for i in rec)
    total_pag  = sum(_valor(i) for i in pag)
    atrasados  = [i for i in rec if i.get("status") == "ATRASADO"]

    return {
        "nome":          nome,
        "pessoas":       pessoas[:3],
        "a_receber":     round(total_rec, 2),
        "a_pagar":       round(total_pag, 2),
        "parcelas_rec":  len(rec),
        "parcelas_pag":  len(pag),
        "atrasados":     len(atrasados),
        "itens_rec":     rec[:10],
        "itens_pag":     pag[:10],
    }


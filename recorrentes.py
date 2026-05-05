"""Detecção de lançamentos recorrentes e sugestão de relançamento."""
import json, os, re
from datetime import date, timedelta
from consulta_financeira import _buscar, _valor

_CACHE_FILE = "recorrentes_cache.json"


def _normalizar(texto: str) -> str:
    """Remove números, datas e espaços extras para comparar títulos."""
    t = (texto or "").lower()
    t = re.sub(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", "", t)   # datas
    t = re.sub(r"\b\d+\b", "", t)                             # números soltos
    t = re.sub(r"\s+", " ", t).strip()
    return t


def detectar_recorrentes(meses: int = 3) -> list[dict]:
    """
    Analisa os últimos `meses` meses e devolve lançamentos que apareceram
    em pelo menos 2 meses com valor similar (±20%).
    Retorna lista de {titulo_norm, tipo, valor_medio, ultimo_vencimento, sugerido_proximo}.
    """
    hoje  = date.today()
    ini   = (hoje.replace(day=1) - timedelta(days=30 * meses))
    fim   = hoje

    p = {"data_vencimento_de": str(ini), "data_vencimento_ate": str(fim)}
    rec = [{"tipo": "RECEBER", **i} for i in _buscar("contas-a-receber/buscar", p)]
    pag = [{"tipo": "PAGAR",   **i} for i in _buscar("contas-a-pagar/buscar",   p)]
    todos = rec + pag

    # Agrupa por título normalizado + tipo
    grupos: dict[str, list] = {}
    for item in todos:
        chave = _normalizar(item.get("descricao", "")) + "|" + item.get("tipo", "")
        if not chave.startswith("|"):
            grupos.setdefault(chave, []).append(item)

    recorrentes = []
    proximo_mes_ini = str(hoje.replace(day=1) + timedelta(days=32)).replace(
        str((hoje.replace(day=1) + timedelta(days=32)).day).zfill(2), "01"
    )
    # proximo_mes_ini mais simples:
    if hoje.month == 12:
        proximo = hoje.replace(year=hoje.year + 1, month=1, day=1)
    else:
        proximo = hoje.replace(month=hoje.month + 1, day=1)

    for chave, itens in grupos.items():
        if len(itens) < 2:
            continue

        # Verifica se apareceu em pelo menos 2 meses distintos
        meses_presentes = set()
        for i in itens:
            venc = i.get("data_vencimento", "")
            if len(venc) >= 7:
                meses_presentes.add(venc[:7])  # "YYYY-MM"

        if len(meses_presentes) < 2:
            continue

        valores = [_valor(i) for i in itens if _valor(i) > 0]
        if not valores:
            continue

        valor_medio = sum(valores) / len(valores)
        # Filtra outliers: mantém apenas valores dentro de ±20% da média
        valores_ok  = [v for v in valores if abs(v - valor_medio) / valor_medio <= 0.20]
        if not valores_ok:
            continue
        valor_medio = sum(valores_ok) / len(valores_ok)

        # Já tem lançamento no próximo mês?
        ja_lancado = any(
            i.get("data_vencimento", "")[:7] == proximo.strftime("%Y-%m")
            for i in itens
        )
        if ja_lancado:
            continue

        ultimo = max(itens, key=lambda i: i.get("data_vencimento", ""))
        titulo_norm = chave.split("|")[0].strip()
        tipo        = ultimo.get("tipo", "PAGAR")

        # Sugere data: mesmo dia do mês do último
        ultimo_venc = ultimo.get("data_vencimento", "")
        try:
            dia = int(ultimo_venc.split("-")[2])
        except Exception:
            dia = 1
        from calendar import monthrange
        dia = min(dia, monthrange(proximo.year, proximo.month)[1])
        data_sugerida = proximo.replace(day=dia)

        recorrentes.append({
            "titulo_norm":        titulo_norm,
            "titulo_original":    (ultimo.get("descricao") or titulo_norm)[:50],
            "tipo":               tipo,
            "valor_medio":        round(valor_medio, 2),
            "ocorrencias":        len(meses_presentes),
            "ultimo_vencimento":  ultimo_venc,
            "data_sugerida":      str(data_sugerida),
        })

    # Ordena por valor decrescente (mais relevantes primeiro)
    return sorted(recorrentes, key=lambda x: -x["valor_medio"])


def salvar_ignorados(titulos: list[str]):
    """Persiste títulos que o usuário não quer mais ser notificado."""
    try:
        dados = json.load(open(_CACHE_FILE)) if os.path.exists(_CACHE_FILE) else {}
        dados["ignorados"] = list(set(dados.get("ignorados", []) + titulos))
        json.dump(dados, open(_CACHE_FILE, "w"), ensure_ascii=False)
    except Exception as e:
        print(f"[RECORRENTES] Erro ao salvar ignorados: {e}")


def get_ignorados() -> set[str]:
    try:
        dados = json.load(open(_CACHE_FILE)) if os.path.exists(_CACHE_FILE) else {}
        return set(dados.get("ignorados", []))
    except Exception:
        return set()

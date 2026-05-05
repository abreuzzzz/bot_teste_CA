"""Comparação de dois períodos mensais lado a lado."""
from datetime import date, timedelta
from consulta_financeira import resumo_mes


def _parse_mes(texto: str) -> date | None:
    """
    Aceita: 'abr', 'abril', '04', '04/2026', '2026-04', 'abril/2026'
    Retorna primeiro dia do mês ou None.
    """
    import re
    MESES_PT = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
        "janeiro": 1, "fevereiro": 2, "março": 3, "março": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    hoje = date.today()
    texto = texto.strip().lower()

    # "04/2026" ou "2026-04"
    m = re.match(r"(\d{1,2})[/\-](\d{4})", texto)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)
    m = re.match(r"(\d{4})[/\-](\d{1,2})", texto)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)

    # "abr/2026" ou "abril/2026"
    m = re.match(r"([a-zç]+)[/\s]+(\d{4})", texto)
    if m:
        mes_n = MESES_PT.get(m.group(1))
        if mes_n:
            return date(int(m.group(2)), mes_n, 1)

    # só mês por extenso: "abr", "abril"
    mes_n = MESES_PT.get(texto)
    if mes_n:
        ano = hoje.year if mes_n <= hoje.month else hoje.year - 1
        return date(ano, mes_n, 1)

    # só número: "04"
    m = re.match(r"^(\d{1,2})$", texto)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 12:
            ano = hoje.year if n <= hoje.month else hoje.year - 1
            return date(ano, n, 1)

    return None


def comparar(periodo_a: str, periodo_b: str) -> dict | None:
    """
    Compara dois períodos mensais.
    Retorna dict com resumo de cada um + variações percentuais.
    """
    mes_a = _parse_mes(periodo_a)
    mes_b = _parse_mes(periodo_b)
    if not mes_a or not mes_b:
        return None

    r_a = resumo_mes(mes_a)
    r_b = resumo_mes(mes_b)

    def _var(a: float, b: float) -> float:
        if b == 0:
            return 0.0
        return round((a - b) / abs(b) * 100, 1)

    def _seta(v: float) -> str:
        return "▲" if v > 0 else ("▼" if v < 0 else "━")

    campos = ["total_receber", "total_pagar", "recebido", "pago", "resultado"]
    variacoes = {c: _var(r_a[c], r_b[c]) for c in campos}

    return {
        "label_a":   mes_a.strftime("%m/%Y"),
        "label_b":   mes_b.strftime("%m/%Y"),
        "resumo_a":  r_a,
        "resumo_b":  r_b,
        "variacoes": variacoes,
        "seta":      {c: _seta(variacoes[c]) for c in campos},
    }


def formatar_comparacao(c: dict) -> str:
    la, lb = c["label_a"], c["label_b"]
    ra, rb = c["resumo_a"], c["resumo_b"]
    v, s   = c["variacoes"], c["seta"]

    def linha(label: str, campo: str) -> str:
        va = ra[campo]
        vb = rb[campo]
        pct = v[campo]
        return (f"  {label:<14} R$ {vb:>9,.2f}  →  R$ {va:>9,.2f}  "
                f"{s[campo]} {abs(pct):.1f}%")

    emoji = "✅" if ra["resultado"] >= rb["resultado"] else "🔴"
    return (
        f"📊 *Comparação: {lb} vs {la}*\n\n"
        f"{'Campo':<14} {'  ' + lb:>14}    {'  ' + la:>14}\n"
        f"{linha('A Receber', 'total_receber')}\n"
        f"{linha('A Pagar',   'total_pagar')}\n"
        f"{linha('Recebido',  'recebido')}\n"
        f"{linha('Pago',      'pago')}\n"
        f"{'─' * 50}\n"
        f"{linha('Resultado', 'resultado')}\n\n"
        f"{emoji} Variação do resultado: {s['resultado']} {abs(v['resultado']):.1f}%"
    )

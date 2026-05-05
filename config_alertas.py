"""Configuração de alertas por chat — liga/desliga notificações individuais."""
import json, os

_FILE = "config_alertas.json"

# Alertas disponíveis com label e estado padrão (todos ligados)
ALERTAS_DISPONIVEIS = {
    "briefing":     "☀️ Briefing matinal (08:00)",
    "vencimento":   "⚠️ Alertas D-1 / D-3 de vencimento",
    "recebimentos": "📥 Inadimplência / recebimentos atrasados",
    "projecao":     "🔴 Alerta de caixa negativo",
    "recorrentes":  "🔄 Sugestão de lançamentos recorrentes (seg)",
    "semanal":      "📊 Resumo semanal visual (sex 17h)",
    "mensal":       "📅 Relatório mensal (último dia)",
    "orcamento":    "💰 Alertas de orçamento",
    "fechamento":   "🌆 Fechamento do dia (17h)",
}


def _carregar() -> dict:
    if not os.path.exists(_FILE):
        return {}
    try:
        return json.load(open(_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _salvar(dados: dict):
    json.dump(dados, open(_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def get_config(chat_id: int) -> dict:
    """Retorna configuração do chat; padrão = tudo ativo."""
    dados = _carregar()
    return dados.get(str(chat_id), {k: True for k in ALERTAS_DISPONIVEIS})


def set_alerta(chat_id: int, alerta: str, ativo: bool):
    """Liga ou desliga um tipo de alerta para o chat."""
    dados = _carregar()
    cfg   = dados.get(str(chat_id), {k: True for k in ALERTAS_DISPONIVEIS})
    cfg[alerta] = ativo
    dados[str(chat_id)] = cfg
    _salvar(dados)


def is_ativo(chat_id: int, alerta: str) -> bool:
    """Verifica se um alerta está ativo para o chat."""
    return get_config(chat_id).get(alerta, True)

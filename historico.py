"""Histórico de ações do bot — trilha de auditoria local."""
import json, os
from datetime import datetime

_FILE = "historico_acoes.json"
_MAX  = 200   # máximo de registros mantidos


def registrar(acao: str, descricao: str, chat_id: int, extra: dict = None):
    """Adiciona uma entrada ao histórico."""
    try:
        dados = _carregar()
        dados.append({
            "ts":        datetime.now().strftime("%Y-%m-%d %H:%M"),
            "acao":      acao,
            "descricao": descricao[:120],
            "chat_id":   chat_id,
            "extra":     extra or {},
        })
        # Mantém apenas os últimos _MAX
        if len(dados) > _MAX:
            dados = dados[-_MAX:]
        _salvar(dados)
    except Exception as e:
        print(f"[HIST] Erro ao registrar: {e}")


def listar(chat_id: int, limite: int = 15) -> list[dict]:
    """Retorna os últimos registros do chat_id."""
    try:
        dados = _carregar()
        filtrado = [d for d in dados if d.get("chat_id") == chat_id]
        return list(reversed(filtrado[-limite:]))
    except Exception:
        return []


def _carregar() -> list:
    if not os.path.exists(_FILE):
        return []
    try:
        return json.load(open(_FILE, encoding="utf-8"))
    except Exception:
        return []


def _salvar(dados: list):
    json.dump(dados, open(_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

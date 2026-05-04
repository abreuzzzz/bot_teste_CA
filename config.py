import os

TELEGRAM_TOKEN           = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY           = os.environ["GEMINI_API_KEY"]
CONTA_AZUL_CLIENT_ID     = os.environ["CONTA_AZUL_CLIENT_ID"]
CONTA_AZUL_CLIENT_SECRET = os.environ["CONTA_AZUL_CLIENT_SECRET"]

# Suporte a múltiplos chats/grupos separados por vírgula
# Ex: TELEGRAM_ALLOWED_CHAT_IDS="-1001234567890,987654321"
# Retrocompatível: se só existir TELEGRAM_ALLOWED_CHAT_ID (singular), usa ele
_ids_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
if _ids_raw:
    TELEGRAM_ALLOWED_CHAT_IDS = [int(x.strip()) for x in _ids_raw.split(",") if x.strip()]
else:
    TELEGRAM_ALLOWED_CHAT_IDS = [int(os.environ["TELEGRAM_ALLOWED_CHAT_ID"])]

# Mantido por compatibilidade com código legado que ainda referencie a variável singular
TELEGRAM_ALLOWED_CHAT_ID = TELEGRAM_ALLOWED_CHAT_IDS[0]

# Opcional: nome preferencial para aparecer primeiro nas sugestões
BOOST_CONTA              = os.environ.get("SUGESTAO_BOOST_CONTA", "")
BOOST_CATEGORIA_RECEITA  = os.environ.get("SUGESTAO_BOOST_CATEGORIA_RECEITA", "")
BOOST_CATEGORIA_DESPESA  = os.environ.get("SUGESTAO_BOOST_CATEGORIA_DESPESA", "")

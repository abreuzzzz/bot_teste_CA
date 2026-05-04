import os

TELEGRAM_TOKEN           = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_ALLOWED_CHAT_ID"])
GEMINI_API_KEY           = os.environ["GEMINI_API_KEY"]
CONTA_AZUL_CLIENT_ID     = os.environ["CONTA_AZUL_CLIENT_ID"]
CONTA_AZUL_CLIENT_SECRET = os.environ["CONTA_AZUL_CLIENT_SECRET"]

# Opcional: nome preferencial para aparecer primeiro nas sugestões
BOOST_CONTA              = os.environ.get("SUGESTAO_BOOST_CONTA", "")
BOOST_CATEGORIA_RECEITA  = os.environ.get("SUGESTAO_BOOST_CATEGORIA_RECEITA", "")
BOOST_CATEGORIA_DESPESA  = os.environ.get("SUGESTAO_BOOST_CATEGORIA_DESPESA", "")

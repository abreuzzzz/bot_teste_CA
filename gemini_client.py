import google.generativeai as genai
from config import GEMINI_API_KEY
import json, re
from datetime import date

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

SYSTEM = """
Você é um assistente financeiro especializado. Quando o usuário descrever um lançamento,
extraia os dados e retorne SOMENTE um JSON válido com os campos:
{
  "acao": "RECEBER" | "PAGAR" | "CONSULTA" | "BAIXA" | "INDEFINIDO",
  "titulo": string,
  "valor": float,
  "vencimento": "YYYY-MM-DD",
  "parcelas": int (padrão 1),
  "termo_extra": string (palavras-chave para sugerir conta/categoria/centro),
  "mensagem": string (resposta amigável ao usuário)
}
Se não for um lançamento (for uma pergunta ou consulta), retorne acao=CONSULTA e mensagem com a resposta.
Hoje é: {hoje}
"""

def extrair_lancamento(texto: str) -> dict:
    prompt = SYSTEM.replace("{hoje}", str(date.today()))
    resp   = model.generate_content(f"{prompt}\n\nMensagem do usuário: {texto}")
    raw    = resp.text.strip()
    # Remove markdown code blocks se houver
    raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except Exception:
        return {"acao": "INDEFINIDO", "mensagem": raw}


def extrair_de_imagem(imagem_bytes: bytes, mime: str = "image/jpeg") -> dict:
    img_part = {"mime_type": mime, "data": imagem_bytes}
    prompt   = SYSTEM.replace("{hoje}", str(date.today())) + "\n\nExtraia os dados do documento na imagem."
    resp     = model.generate_content([prompt, img_part])
    raw      = resp.text.strip()
    raw      = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except Exception:
        return {"acao": "INDEFINIDO", "mensagem": raw}


def responder_consulta(pergunta: str, contexto_financeiro: str) -> str:
    prompt = (
        f"Você é um assistente financeiro. Responda de forma clara e objetiva.\n"
        f"Dados financeiros disponíveis:\n{contexto_financeiro}\n\n"
        f"Pergunta: {pergunta}"
    )
    return model.generate_content(prompt).text

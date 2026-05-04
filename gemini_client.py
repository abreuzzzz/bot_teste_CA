import google.generativeai as genai
from config import GEMINI_API_KEY
import json, re, time
from datetime import date

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash-lite")

SYSTEM = """
Você é um assistente financeiro especializado. Analise a mensagem do usuário e retorne SOMENTE um JSON válido.

Campos obrigatórios:
{
  "acao": string,
  "titulo": string,
  "valor": float,
  "vencimento": "YYYY-MM-DD",
  "parcelas": int,
  "termo_extra": string,
  "mensagem": string
}

Valores possíveis para "acao":
- "RECEBER"   → usuário quer lançar uma receita/recebimento
- "PAGAR"     → usuário quer lançar uma despesa/pagamento
- "BAIXA"     → usuário quer dar baixa em um lançamento existente
- "PENDENTES" → usuário quer ver contas a vencer (ex: "quais contas vencem essa semana?", "o que tenho para pagar?")
- "ATRASADOS" → usuário quer ver contas atrasadas (ex: "tenho algo atrasado?", "contas em atraso")
- "RELATORIO" → usuário quer resumo financeiro (ex: "como estão as finanças?", "resumo do mês", "quanto entrou esse mês?")
- "CONSULTA"  → pergunta financeira que precisa de análise dos dados (ex: "qual meu saldo?", "quanto gastei com X?")
- "INDEFINIDO"→ não foi possível identificar

Regras:
- Se for RECEBER ou PAGAR, extraia título, valor, vencimento e parcelas
- Se não houver vencimento, use a data de hoje
- Para PENDENTES, ATRASADOS e RELATORIO, não precisa preencher os outros campos
- Para CONSULTA, coloque a pergunta original em "mensagem"
- "termo_extra" = palavras-chave úteis para sugerir conta/categoria (ex: "luz", "aluguel", "João")
- Hoje é: {hoje}
"""


def _gerar(prompt: str, max_tentativas: int = 3) -> str:
    for tentativa in range(1, max_tentativas + 1):
        try:
            return model.generate_content(prompt).text.strip()
        except Exception as e:
            msg = str(e)
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()) and tentativa < max_tentativas:
                espera = 35
                m = re.search(r"retry in (\d+)", msg)
                if m:
                    espera = int(m.group(1)) + 5
                print(f"[GEMINI] Quota excedida. Aguardando {espera}s (tentativa {tentativa}/{max_tentativas})...")
                time.sleep(espera)
                continue
            raise
    raise Exception("Gemini: máximo de tentativas atingido.")


def _parse(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except Exception:
        return {"acao": "INDEFINIDO", "mensagem": raw}


def extrair_lancamento(texto: str) -> dict:
    prompt = SYSTEM.replace("{hoje}", str(date.today()))
    try:
        raw = _gerar(f"{prompt}\n\nMensagem do usuário: {texto}")
        return _parse(raw)
    except Exception as e:
        print(f"[GEMINI] Erro: {e}")
        return {
            "acao":     "INDEFINIDO",
            "mensagem": "⚠️ IA temporariamente indisponível. Tente em alguns minutos ou use /manual.",
        }


def extrair_de_imagem(imagem_bytes: bytes, mime: str = "image/jpeg") -> dict:
    img_part = {"mime_type": mime, "data": imagem_bytes}
    prompt   = SYSTEM.replace("{hoje}", str(date.today())) + "\n\nExtraia os dados do documento na imagem."
    try:
        for tentativa in range(1, 4):
            try:
                resp = model.generate_content([prompt, img_part])
                return _parse(resp.text.strip())
            except Exception as e:
                if ("429" in str(e) or "quota" in str(e).lower()) and tentativa < 3:
                    time.sleep(35)
                    continue
                raise
    except Exception as e:
        print(f"[GEMINI] Erro imagem: {e}")
        return {"acao": "INDEFINIDO", "mensagem": "⚠️ IA indisponível. Use /manual."}


def responder_consulta(pergunta: str, contexto_financeiro: str) -> str:
    prompt = (
        f"Você é um assistente financeiro. Responda de forma clara e objetiva em português.\n"
        f"Dados financeiros disponíveis:\n{contexto_financeiro}\n\n"
        f"Pergunta: {pergunta}"
    )
    try:
        return _gerar(prompt)
    except Exception as e:
        print(f"[GEMINI] Erro consulta: {e}")
        return "⚠️ IA temporariamente indisponível. Tente novamente em alguns minutos."

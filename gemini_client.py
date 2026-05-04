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
  "mensagem": string,
  "categoria": string,
  "periodo": string,
  "limite": float
}

Valores possíveis para "acao":
- "RECEBER"   → lançar receita/recebimento
- "PAGAR"     → lançar despesa/pagamento
- "BAIXA"     → dar baixa em um lançamento existente (ex: "paguei o aluguel", "dei baixa na luz")
- "PENDENTES" → contas a vencer
- "ATRASADOS" → contas em atraso
- "RELATORIO" → resumo financeiro
- "CONSULTA"  → pergunta financeira que precisa análise
- "GRAFICO"   → usuário quer visualizar gráfico (ex: "me mostra um gráfico", "gráfico de despesas", "fluxo de caixa visual")
- "ORCAMENTO" → ver/definir orçamento (ex: "definir orçamento mercado 800", "como está meu orçamento?")
- "BUSCA"     → busca livre por termo (ex: "quanto paguei pra X em 2026?", "busca fornecedor Y")
- "EXPORT"    → exportar planilha (ex: "exportar mai/2026", "planilha do mês")
- "INDEFINIDO"→ não foi possível identificar

Regras:
- RECEBER/PAGAR: extraia título, valor, vencimento e parcelas. Sem vencimento explícito, use hoje.
- BAIXA: preencha "termo_extra" com o que identifica a parcela (nome/descrição).
- GRAFICO: em "termo_extra" coloque o tipo: "meses" (padrão), "categoria_despesa", "categoria_receita", "fluxo_caixa".
- ORCAMENTO: se for definição, preencha "categoria" e "limite". Se for consulta, deixe ambos vazios.
- BUSCA: "termo_extra" = palavra-chave a buscar. "periodo" pode conter ano (ex: "2026") ou ficar vazio.
- EXPORT: "periodo" = ex "mai2026", "05/2026". Vazio = mês atual.
- CONSULTA: coloque a pergunta original em "mensagem".
- "termo_extra" sempre = palavras-chave úteis.
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
                print(f"[GEMINI] Quota excedida. Aguardando {espera}s ({tentativa}/{max_tentativas})...")
                time.sleep(espera)
                continue
            raise
    raise Exception("Gemini: máximo de tentativas atingido.")


def _parse(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except Exception:
        return {"acao": "INDEFINIDO",
                "mensagem": "Não consegui interpretar. Tente reformular ou use /manual."}


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
    for tentativa in range(1, 4):
        try:
            resp = model.generate_content([prompt, img_part])
            return _parse(resp.text.strip())
        except Exception as e:
            if ("429" in str(e) or "quota" in str(e).lower()) and tentativa < 3:
                time.sleep(35)
                continue
            print(f"[GEMINI] Erro imagem: {e}")
            return {"acao": "INDEFINIDO", "mensagem": "⚠️ IA indisponível. Use /manual."}
    return {"acao": "INDEFINIDO", "mensagem": "⚠️ IA indisponível."}


def transcrever_audio(audio_bytes: bytes, mime: str = "audio/ogg") -> str:
    """Transcreve áudio em texto puro usando Gemini."""
    audio_part = {"mime_type": mime, "data": audio_bytes}
    prompt = "Transcreva o áudio em português brasileiro. Retorne SOMENTE a transcrição, sem comentários."
    for tentativa in range(1, 3):
        try:
            return model.generate_content([prompt, audio_part]).text.strip()
        except Exception as e:
            if ("429" in str(e) or "quota" in str(e).lower()) and tentativa < 2:
                time.sleep(35)
                continue
            print(f"[GEMINI] Erro áudio: {e}")
            return ""
    return ""


def extrair_de_audio(audio_bytes: bytes, mime: str = "audio/ogg") -> tuple[str, dict]:
    """Transcreve + interpreta. Retorna (transcricao, dados)."""
    texto = transcrever_audio(audio_bytes, mime)
    if not texto:
        return "", {"acao": "INDEFINIDO", "mensagem": "⚠️ Não consegui entender o áudio."}
    return texto, extrair_lancamento(texto)


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

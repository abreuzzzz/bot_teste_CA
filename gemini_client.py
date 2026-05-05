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
  "limite": float,
  "cliente": string
}

Valores possíveis para "acao":
- "RECEBER"        → lançar receita/recebimento
- "PAGAR"          → lançar despesa/pagamento
- "BAIXA"          → dar baixa em lançamento (ex: "paguei o aluguel", "recebi do Pedro", "dei baixa na luz")
- "BAIXA_POR_VALOR" → quando só cita valor (ex: "recebi 500 reais", "paguei 200")
- "BAIXA_LOTE"     → baixar tudo que vence hoje (ex: "paguei tudo", "quitei tudo de hoje")
- "CANCELAR_ULTIMO" → desfazer/cancelar o último lançamento feito (ex: "cancela o último", "desfaz o que lancei")
- "EDITAR_PARCELA" → editar/alterar dados de parcela existente
- "PENDENTES"      → contas a vencer
- "ATRASADOS"      → contas em atraso
- "RELATORIO"      → resumo financeiro
- "SALDO"          → saldo das contas (ex: "qual meu saldo?", "to no vermelho?", "tenho dinheiro?")
- "TRANSFERENCIAS" → transferências entre contas
- "CONSULTA"       → pergunta financeira analítica (ex: "quanto gastei com X?", "qual meu maior cliente?", "tenho dinheiro pra Y?")
- "GRAFICO"        → visualizar gráfico
- "ORCAMENTO"      → ver/definir orçamento
- "BUSCA"          → busca livre por termo
- "EXPORT"         → exportar planilha
- "FAVORITOS"      → ver/usar favoritos/templates (ex: "meus favoritos", "lançar favorito aluguel")
- "FAVORITO_SALVAR" → salvar lançamento como favorito
- "DRE"            → demonstrativo de resultado (ex: "dre", "resultado por categoria", "dre de abril", "quanto gastei por categoria")
- "AGING"          → aging de recebíveis/pagáveis (ex: "aging", "inadimplência", "quanto estou devendo fora do prazo", "recebíveis em atraso")
- "EXTRATO_CLIENTE" → histórico completo de parcelas de um cliente (ex: "extrato do João", "histórico do fornecedor X", "tudo do cliente Silva")
- "COMPARAR"       → comparar dois meses (ex: "compare abril com março", "como foi abril vs março?", "diferença entre mai e abr")
- "META"           → consultar ou definir meta de faturamento (ex: "meta do mês", "definir meta 20000", "quanto falta pra meta?")
- "META_DEFINIR"   → definir nova meta (ex: "meta de receita 15000", "quero faturar 20 mil")
- "HISTORICO"      → histórico de ações do bot (ex: "o que o bot fez?", "últimas ações", "histórico")
- "CONFIG_ALERTAS" → configurar notificações (ex: "configurar alertas", "desligar briefing", "notificações")
- "PROJECAO"       → projeção de caixa (ex: "como vai meu caixa?", "vai faltar dinheiro?", "projeção")
- "CLIENTE"        → saldo aberto de um cliente/fornecedor (ex: "quanto o João me deve?", "saldo do fornecedor X")
- "FECHAR_MES"     → checklist de fechamento (ex: "fechar mês", "checklist", "pronto pra fechar?")
- "RECORRENTES"    → lançamentos recorrentes (ex: "o que se repete?", "recorrentes")
- "INDEFINIDO"     → não identificado

Regras:
- RECEBER/PAGAR: extraia título, valor, vencimento e parcelas. Sem vencimento explícito, use hoje. "em Nx"/"Nx vezes" → "parcelas": N.
- BAIXA: preencha "termo_extra" com o que identifica a parcela (nome/descrição).
- BAIXA_POR_VALOR: preencha "valor" com o valor mencionado. Sem descritor específico. Ex: "recebi 500" → acao=BAIXA_POR_VALOR, valor=500.0
- BAIXA_LOTE: sem campos adicionais necessários.
- CANCELAR_ULTIMO: sem campos adicionais.
- SALDO: inclui perguntas do tipo "to no vermelho?", "tenho dinheiro pra pagar X?", "qual meu saldo?".
- CONSULTA: use para perguntas analíticas com período ou categoria. Inclua a pergunta em "mensagem". Exemplos: "quanto gastei com fornecedores em abril?", "qual meu maior cliente esse mês?", "quando meu saldo vai zerar?", "tenho dinheiro pra pagar o 13°?"
- DRE: "periodo" = mês se mencionado (ex: "abr", "abril/2026"). Sem mês = mês atual.
- AGING: "termo_extra" = "RECEBER" (padrão) ou "PAGAR" se explícito.
- EXTRATO_CLIENTE: "cliente" = nome do cliente/fornecedor. "periodo" = ano se mencionado.
- COMPARAR: "periodo" = primeiro mês, "termo_extra" = segundo mês. Ex: "compare abril com março" → periodo="abril", termo_extra="março".
- META: consulta → sem campos. META_DEFINIR: "valor" = valor da meta, "termo_extra" = "receita" | "resultado".
- HISTORICO: sem campos adicionais.
- CONFIG_ALERTAS: sem campos adicionais (o bot vai mostrar o menu).
- PROJECAO: "limite" = dias de projeção (padrão 15, se usuário especificar outro).
- CLIENTE: "cliente" = nome do cliente/fornecedor.
- FECHAR_MES: sem campos adicionais.
- RECORRENTES: sem campos adicionais.
- GRAFICO: "termo_extra" = "meses" | "categoria_despesa" | "categoria_receita" | "fluxo_caixa".
- ORCAMENTO: definição → preencha "categoria" e "limite"; consulta → ambos vazios.
- BUSCA: "termo_extra" = palavra-chave; "cliente" = nome se mencionado; "periodo" = ano se presente.
- EXPORT: "periodo" = ex "mai2026"; "termo_extra" = tipo/status.
- FAVORITOS: "termo_extra" = nome do favorito se especificado.
- FAVORITO_SALVAR: "titulo" = nome dado pelo usuário ao favorito.
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
    """Feature 10: Consulta financeira rica com contexto completo."""
    prompt = (
        f"Você é um assistente financeiro pessoal. Responda de forma clara, direta e amigável em português.\n"
        f"Use números concretos da situação do usuário quando disponíveis.\n"
        f"Se perguntarem 'to no vermelho?' ou similar, seja direto: sim/não + saldo atual.\n"
        f"Se perguntarem sobre capacidade de pagamento, calcule e responda objetivamente.\n"
        f"Não use markdown, seja conciso (máx 5 linhas).\n\n"
        f"Dados financeiros do usuário:\n{contexto_financeiro}\n\n"
        f"Pergunta: {pergunta}"
    )
    try:
        return _gerar(prompt)
    except Exception as e:
        print(f"[GEMINI] Erro consulta: {e}")
        return "⚠️ IA temporariamente indisponível. Tente novamente em alguns minutos."

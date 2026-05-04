from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from catalogo import contas_financeiras, categorias_receita, categorias_despesa, centros_custo
from sugestao import sugerir_conta, sugerir_categoria, sugerir_centro, match_livre, top3

estados: dict = {}
AGUARDANDO_LIVRE = "aguardando_livre"
AGUARDANDO_EDIT  = "aguardando_edit"

# Campos de texto editáveis (não usam o fluxo de seleção do catálogo)
CAMPOS_TEXTO = {
    "titulo":     "Título / descrição",
    "valor":      "Valor (R$)",
    "vencimento": "Data de vencimento (DD/MM/AAAA)",
    "parcelas":   "Número de parcelas",
}
# Campos que reusam o fluxo de seleção do catálogo
CAMPOS_SELECAO = {
    "conta":        "Conta Financeira",
    "categoria":    "Categoria",
    "centro_custo": "Centro de Custo",
}


# ─── Helpers de callback_data ────────────────────────────────────────────────

def _cb(etapa: str, idx, chat_id: int) -> str:
    return f"sel:{etapa}:{idx}:{chat_id}"


def _salvar_opcoes(context, chat_id: int, etapa: str, lista: list):
    if "opcoes" not in context.user_data:
        context.user_data["opcoes"] = {}
    context.user_data["opcoes"][etapa] = lista


def _opcao(context, etapa: str, idx: int) -> dict:
    return context.user_data.get("opcoes", {}).get(etapa, [])[idx]


def limpar_estado(chat_id: int):
    """Chamada externa após confirmação/cancelamento do lançamento."""
    estados.pop(chat_id, None)


# ─── Entrada pública ──────────────────────────────────────────────────────────

async def iniciar_selecao(update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict):
    chat_id = update.message.chat_id
    estados[chat_id] = {
        "etapa": "conta",
        "dados": {
            **dados,
            "conta_id":       None, "conta_nome":       None,
            "categoria_id":   None, "categoria_nome":   None,
            "centro_id":      None, "centro_nome":      None,
        },
    }
    await _perguntar(update.message, context, chat_id)


async def callback_selecao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if chat_id not in estados:
        await query.edit_message_text("⚠️ Sessão expirada. Refaça o lançamento.")
        return

    partes  = query.data.split(":")
    etapa   = partes[1]
    idx_str = partes[2]
    estado  = estados[chat_id]

    if idx_str == "LIVRE":
        estado["etapa"]       = AGUARDANDO_LIVRE
        estado["etapa_livre"] = etapa
        estado["lista_livre"] = _lista_para(etapa, estado["dados"]["tipo"])
        await query.edit_message_text(
            f"✏️ Digite o nome da *{_label(etapa)}* desejada\n"
            f"_(ou parte do nome — vou fazer o match automaticamente)_",
            parse_mode="Markdown",
        )
        return

    if idx_str == "PULAR":
        _salvar(estado, etapa, None, None)
        await query.edit_message_text(f"⏭️ *{_label(etapa)}* pulada.", parse_mode="Markdown")
    else:
        item = _opcao(context, etapa, int(idx_str))
        _salvar(estado, etapa, item["id"], item["nome"])
        await query.edit_message_text(
            f"✅ *{_label(etapa)}* selecionada: *{item['nome']}*",
            parse_mode="Markdown",
        )

    await _avancar(query, context, chat_id)


# ─── Texto livre (seleção por nome OU edição de campo) ──────────────────────

async def receber_texto_livre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.message.chat_id
    estado  = estados.get(chat_id)
    if not estado:
        return False

    etapa = estado.get("etapa")

    # ── Edição de campo de texto ─────────────────────────────────────────────
    if etapa == AGUARDANDO_EDIT:
        await _aplicar_edit_texto(update, context, estado)
        return True

    # ── Seleção livre (digitar nome de conta/categoria/centro) ───────────────
    if etapa != AGUARDANDO_LIVRE:
        return False

    texto = update.message.text.strip()
    etapa_livre = estado["etapa_livre"]
    lista       = estado["lista_livre"]

    match = match_livre(lista, texto)
    if match:
        _salvar(estado, etapa_livre, match["id"], match["nome"])
        await update.message.reply_text(
            f"✅ Encontrei: *{match['nome']}*", parse_mode="Markdown",
        )
        estado["etapa"] = etapa_livre
        await _avancar(update, context, chat_id)
    else:
        sugestoes = top3(lista, texto)
        if sugestoes:
            _salvar_opcoes(context, chat_id, etapa_livre, sugestoes)
            botoes = [
                [InlineKeyboardButton(s["nome"], callback_data=_cb(etapa_livre, idx, chat_id))]
                for idx, s in enumerate(sugestoes)
            ]
            botoes.append([InlineKeyboardButton("⏭️ Pular",
                                                callback_data=_cb(etapa_livre, "PULAR", chat_id))])
            await update.message.reply_text(
                f'🔍 Não achei exatamente *"{texto}"*. Você quis dizer?',
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes),
            )
        else:
            await update.message.reply_text(
                "❌ Nenhum resultado. Tente novamente ou use /catalogo."
            )
    return True


# ─── Callback de edição ──────────────────────────────────────────────────────

async def callback_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Padrões:
       edit:menu:<chat_id>          — abre menu de campos
       edit:f:<campo>:<chat_id>     — edita o campo escolhido
       edit:cancel:<chat_id>        — volta para resumo sem alterar
    """
    query = update.callback_query
    await query.answer()
    partes = query.data.split(":")
    acao   = partes[1]
    chat_id = int(partes[-1])

    estado = estados.get(chat_id)
    if not estado:
        # Pode estar só no bot_data (resumo já foi mostrado e estado limpo no fluxo antigo).
        # Restaurar estado a partir de dados salvos:
        dados = context.bot_data.get(f"lancamento_{chat_id}")
        if not dados:
            await query.edit_message_text("⚠️ Sessão expirada. Refaça o lançamento.")
            return
        estado = estados[chat_id] = {"etapa": "edit", "dados": dict(dados)}

    if acao == "menu":
        botoes = [
            [InlineKeyboardButton("📝 Título",     callback_data=f"edit:f:titulo:{chat_id}")],
            [InlineKeyboardButton("💰 Valor",      callback_data=f"edit:f:valor:{chat_id}")],
            [InlineKeyboardButton("📅 Vencimento", callback_data=f"edit:f:vencimento:{chat_id}")],
            [InlineKeyboardButton("🔢 Parcelas",   callback_data=f"edit:f:parcelas:{chat_id}")],
            [InlineKeyboardButton("🏦 Conta",      callback_data=f"edit:f:conta:{chat_id}")],
            [InlineKeyboardButton("📂 Categoria",  callback_data=f"edit:f:categoria:{chat_id}")],
            [InlineKeyboardButton("🏷️ Centro de Custo", callback_data=f"edit:f:centro_custo:{chat_id}")],
            [InlineKeyboardButton("⬅️ Voltar",     callback_data=f"edit:cancel:{chat_id}")],
        ]
        await query.edit_message_text(
            "✏️ *O que deseja editar?*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
        return

    if acao == "cancel":
        await _confirmar(query, context, chat_id, edit_existente=True)
        return

    if acao == "f":
        campo = partes[2]
        if campo in CAMPOS_TEXTO:
            estado["etapa"]       = AGUARDANDO_EDIT
            estado["edit_campo"]  = campo
            await query.edit_message_text(
                f"✏️ Digite o novo valor para *{CAMPOS_TEXTO[campo]}*:",
                parse_mode="Markdown",
            )
        elif campo in CAMPOS_SELECAO:
            estado["etapa"]     = campo
            estado["editando"]  = True   # após escolha, vai direto pro resumo
            await _perguntar(query.message, context, chat_id)
        else:
            await query.edit_message_text("⚠️ Campo desconhecido.")


async def _aplicar_edit_texto(update: Update, context: ContextTypes.DEFAULT_TYPE, estado: dict):
    texto = update.message.text.strip()
    campo = estado.get("edit_campo")
    chat_id = update.message.chat_id

    if campo == "titulo":
        estado["dados"]["titulo"] = texto

    elif campo == "valor":
        try:
            estado["dados"]["valor"] = float(texto.replace(",", ".").replace("R$", "").strip())
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Tente de novo (ex: 250.00).")
            return

    elif campo == "vencimento":
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(texto, fmt)
                estado["dados"]["vencimento"] = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text("❌ Data inválida. Use DD/MM/AAAA.")
            return

    elif campo == "parcelas":
        try:
            estado["dados"]["parcelas"] = max(1, int(texto))
        except ValueError:
            await update.message.reply_text("❌ Digite um número inteiro.")
            return

    estado.pop("edit_campo", None)
    estado["etapa"] = "edit"
    await update.message.reply_text("✅ Atualizado.")
    await _confirmar(update, context, chat_id, edit_existente=False)


# ─── Privados ─────────────────────────────────────────────────────────────────

async def _perguntar(msg_or_query, context, chat_id: int):
    estado = estados[chat_id]
    etapa  = estado["etapa"]
    dados  = estado["dados"]
    tipo   = dados["tipo"]
    termo  = dados.get("termo_extra") or dados["titulo"]

    if etapa == "conta":
        sugestoes = sugerir_conta(termo)
        titulo    = "🏦 *Conta Financeira*"
    elif etapa == "categoria":
        sugestoes = sugerir_categoria(termo, tipo)
        titulo    = "📂 *Categoria*"
    else:
        sugestoes = sugerir_centro(termo)
        titulo    = "🏷️ *Centro de Custo*"

    _salvar_opcoes(context, chat_id, etapa, sugestoes)

    botoes = [
        [InlineKeyboardButton(
            f"{'✅' if i == 0 else '🔹'} {s['nome']}",
            callback_data=_cb(etapa, i, chat_id),
        )]
        for i, s in enumerate(sugestoes)
    ]
    botoes.append([
        InlineKeyboardButton("✏️ Outra (digitar)", callback_data=_cb(etapa, "LIVRE",  chat_id)),
        InlineKeyboardButton("⏭️ Pular",           callback_data=_cb(etapa, "PULAR",  chat_id)),
    ])

    texto = (
        f"{titulo}\n"
        f'Sugestões baseadas em *"{termo}"*:\n\n'
        f"Escolha uma ou clique em *Outra* para digitar:"
    )

    send = getattr(msg_or_query, "reply_text", None) or getattr(msg_or_query, "edit_message_text", None)
    await send(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))


async def _avancar(update_or_query, context, chat_id: int):
    estado = estados[chat_id]
    etapa  = estado["etapa"]

    # Em modo edição, qualquer escolha vai direto para o resumo
    if estado.pop("editando", False):
        await _confirmar(update_or_query, context, chat_id, edit_existente=False)
        return

    if etapa == "conta":
        estado["etapa"] = "categoria"
        await _perguntar(_msg(update_or_query), context, chat_id)

    elif etapa == "categoria":
        if centros_custo():
            estado["etapa"] = "centro_custo"
            await _perguntar(_msg(update_or_query), context, chat_id)
        else:
            await _confirmar(update_or_query, context, chat_id)

    else:
        await _confirmar(update_or_query, context, chat_id)


async def _confirmar(update_or_query, context, chat_id: int, edit_existente: bool = False):
    estado = estados[chat_id]
    dados  = estado["dados"]

    tipo_emoji = "📥" if dados["tipo"] == "RECEBER" else "📤"
    resumo = (
        f"📋 *Resumo do lançamento*\n\n"
        f"{tipo_emoji} *{dados['titulo']}*\n"
        f"💰 R$ {float(dados['valor']):.2f}  ×{dados['parcelas']}x\n"
        f"📅 Vencimento: {dados['vencimento']}\n"
        f"🏦 Conta: {dados['conta_nome'] or '_(padrão)_'}\n"
        f"📂 Categoria: {dados['categoria_nome'] or '_(padrão)_'}\n"
        f"🏷️ Centro: {dados['centro_nome'] or '_(sem centro)_'}\n\n"
        f"Confirma o lançamento?"
    )
    botoes = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data=f"lancar:sim:{chat_id}"),
            InlineKeyboardButton("✏️ Editar",    callback_data=f"edit:menu:{chat_id}"),
        ],
        [InlineKeyboardButton("❌ Cancelar",  callback_data=f"lancar:nao:{chat_id}")],
    ])

    context.bot_data[f"lancamento_{chat_id}"] = dados
    estado["etapa"] = "aguardando_confirmacao"
    # NÃO removemos estados[chat_id] aqui — bot.py limpa via limpar_estado()
    # após o usuário clicar em Confirmar/Cancelar.

    if edit_existente and hasattr(update_or_query, "edit_message_text"):
        try:
            await update_or_query.edit_message_text(
                resumo, parse_mode="Markdown", reply_markup=botoes,
            )
            return
        except Exception:
            pass

    msg = _msg(update_or_query)
    send = getattr(msg, "reply_text", None)
    if send:
        await send(resumo, parse_mode="Markdown", reply_markup=botoes)
    else:
        await update_or_query.message.reply_text(
            resumo, parse_mode="Markdown", reply_markup=botoes,
        )


def _salvar(estado, etapa, id_val, nome):
    if etapa == "conta":
        estado["dados"]["conta_id"]     = id_val
        estado["dados"]["conta_nome"]   = nome
    elif etapa == "categoria":
        estado["dados"]["categoria_id"]   = id_val
        estado["dados"]["categoria_nome"] = nome
    else:
        estado["dados"]["centro_id"]   = id_val
        estado["dados"]["centro_nome"] = nome
    estado["etapa"] = etapa


def _lista_para(etapa: str, tipo: str) -> list:
    if etapa == "conta":     return contas_financeiras()
    if etapa == "categoria": return categorias_receita() if tipo == "RECEBER" else categorias_despesa()
    return centros_custo()


def _label(etapa: str) -> str:
    return {
        "conta":        "Conta Financeira",
        "categoria":    "Categoria",
        "centro_custo": "Centro de Custo",
    }.get(etapa, etapa)


def _msg(update_or_query):
    if hasattr(update_or_query, "message"):
        return update_or_query.message
    return update_or_query

"""
Fluxo do briefing diário e ações rápidas:
  - Feature 1: Briefing personalizado com botões de ação
  - Feature 2: Baixa em 1 toque para vencimentos do dia
  - Feature 3: Baixa em lote ("paguei tudo")
  - Feature 6: Alerta de recebimentos atrasados
"""
from datetime import date, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from consulta_financeira import _valor, pendentes, atrasados, saldo_todas_contas
from baixa_parcela import dar_baixa

# ─── Briefing diário (Feature 1) ─────────────────────────────────────────────

async def enviar_briefing(app, chat_id: int):
    """Envia briefing personalizado com botões de ação rápida."""
    hoje        = date.today()
    dia_semana  = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][hoje.weekday()]
    saudacao    = _saudacao()

    # Contas que vencem HOJE
    vence_hoje = _vencimentos_hoje()

    # Contas que vencem nos próximos 7 dias (excluindo hoje)
    prox_7 = [i for i in pendentes(dias=7)
               if i.get("data_vencimento", "") > str(hoje)][:5]

    # Atrasados
    atras = atrasados()[:5]

    # Saldo total
    try:
        contas = saldo_todas_contas()
        saldo_total = sum(c.get("saldo") or 0 for c in contas)
        saldo_str = f"R$ {saldo_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        saldo_str = "indisponível"

    linhas = [f"{saudacao} *{dia_semana}, {hoje.strftime('%d/%m')}!*\n"]

    # Urgente: hoje
    if vence_hoje:
        total_hoje = sum(_valor(i) for i in vence_hoje)
        linhas.append(
            f"🔴 *HOJE — {len(vence_hoje)} conta(s) a pagar "
            f"(R$ {total_hoje:.2f}):*"
        )
        for i in vence_hoje[:4]:
            desc = (i.get("descricao") or "?")[:30]
            linhas.append(f"  • {desc} — R$ {_valor(i):.2f}")
        if len(vence_hoje) > 4:
            linhas.append(f"  _...e mais {len(vence_hoje) - 4}_")
        linhas.append("")

    # Semana
    if prox_7:
        total_7 = sum(_valor(i) for i in prox_7)
        linhas.append(f"⚠️ *Esta semana: R$ {total_7:.2f} a pagar*")
        for i in prox_7[:3]:
            desc = (i.get("descricao") or "?")[:28]
            venc = i.get("data_vencimento", "")[-5:]  # DD-MM
            linhas.append(f"  • {desc} — {venc}")
        linhas.append("")

    # Atrasados
    if atras:
        total_atras = sum(_valor(i) for i in atras)
        linhas.append(f"🚨 *Atrasados: {len(atras)} (R$ {total_atras:.2f})*")
        linhas.append("")

    if not vence_hoje and not prox_7 and not atras:
        linhas.append("✅ *Tudo em dia! Nenhuma conta urgente.*\n")

    linhas.append(f"💰 Saldo: *{saldo_str}*")

    texto = "\n".join(linhas)

    # Botões de ação rápida
    botoes = []
    if vence_hoje:
        botoes.append([InlineKeyboardButton(
            f"✅ Baixar tudo de hoje ({len(vence_hoje)})",
            callback_data="daily:lote_hoje",
        )])
        # Botão individual para cada vencimento (até 3)
        for idx, i in enumerate(vence_hoje[:3]):
            desc  = (i.get("descricao") or "?")[:22]
            valor = _valor(i)
            botoes.append([InlineKeyboardButton(
                f"💳 {desc} R${valor:.2f}",
                callback_data=f"daily:baixa1:{idx}",
            )])
    botoes.append([
        InlineKeyboardButton("📊 Resumo completo", callback_data="daily:resumo"),
        InlineKeyboardButton("📋 Pendentes",       callback_data="daily:pendentes"),
    ])

    # Salva vencimentos do dia no bot_data para os callbacks
    try:
        app.bot_data[f"vence_hoje_{chat_id}"] = vence_hoje
    except Exception:
        pass

    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes) if botoes else None,
        )
    except Exception as e:
        print(f"[DAILY] Erro envio briefing: {e}")
        # fallback sem markdown
        try:
            await app.bot.send_message(chat_id=chat_id, text=texto.replace("*", "").replace("_", ""))
        except Exception as e2:
            print(f"[DAILY] Falha total: {e2}")


# ─── Callback do briefing (Features 2 e 3) ────────────────────────────────────

async def callback_daily(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    acao    = partes[1]
    chat_id = query.message.chat_id

    if acao == "resumo":
        from scheduler import _relatorio_diario
        await query.edit_message_reply_markup(reply_markup=None)
        await _relatorio_diario(context.application, chat_id)
        return

    if acao == "pendentes":
        await query.edit_message_reply_markup(reply_markup=None)
        itens = pendentes(dias=30)
        if not itens:
            await query.message.reply_text("✅ Nenhuma conta pendente nos próximos 30 dias.")
            return
        linhas = [f"{'📥' if i['tipo'] == 'RECEBER' else '📤'} "
                  f"{(i.get('descricao') or '?')[:32]} — R$ {_valor(i):.2f} ({i.get('data_vencimento', '')})"
                  for i in itens[:20]]
        await query.message.reply_text("📅 *Pendentes (30 dias):*\n\n" + "\n".join(linhas),
                                       parse_mode="Markdown")
        return

    vence_hoje: list = context.application.bot_data.get(f"vence_hoje_{chat_id}", [])

    # ── Baixa em 1 toque (Feature 2) ─────────────────────────────────────────
    if acao == "baixa1":
        idx  = int(partes[2])
        item = vence_hoje[idx] if idx < len(vence_hoje) else None
        if not item:
            await query.edit_message_text("⚠️ Item não encontrado.")
            return
        desc = (item.get("descricao") or "?")[:40]
        v    = _valor(item)
        await query.edit_message_text(
            f"💳 *Confirmar baixa:*\n\n{desc}\nR$ {v:.2f} — hoje ({date.today().strftime('%d/%m/%Y')})",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirmar", callback_data=f"daily:conf_baixa1:{idx}"),
                InlineKeyboardButton("❌ Cancelar",  callback_data="daily:cancelar"),
            ]]),
        )
        return

    if acao == "conf_baixa1":
        idx  = int(partes[2])
        item = vence_hoje[idx] if idx < len(vence_hoje) else None
        if not item:
            await query.edit_message_text("⚠️ Item não encontrado.")
            return
        parcela_id = item.get("id")
        ok = dar_baixa(parcela_id, item.get("tipo", "PAGAR"))
        if ok:
            desc = (item.get("descricao") or "?")[:40]
            await query.edit_message_text(
                f"✅ *Baixa registrada!*\n_{desc}_\nR$ {_valor(item):.2f}",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Falha ao dar baixa. Verifique os logs.")
        return

    # ── Baixa em lote (Feature 3) ─────────────────────────────────────────────
    if acao == "lote_hoje":
        if not vence_hoje:
            await query.edit_message_text("ℹ️ Nenhum vencimento encontrado para hoje.")
            return
        total = sum(_valor(i) for i in vence_hoje)
        linhas = [f"  • {(i.get('descricao') or '?')[:30]} — R$ {_valor(i):.2f}"
                  for i in vence_hoje]
        await query.edit_message_text(
            f"💳 *Baixar TODAS as contas de hoje?*\n\n"
            + "\n".join(linhas)
            + f"\n\n*Total: R$ {total:.2f}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirmar todas", callback_data="daily:conf_lote"),
                InlineKeyboardButton("❌ Cancelar",        callback_data="daily:cancelar"),
            ]]),
        )
        return

    if acao == "conf_lote":
        if not vence_hoje:
            await query.edit_message_text("ℹ️ Nenhuma conta para baixar.")
            return
        await query.edit_message_text("⏳ Dando baixa em todas...")
        ok_count = err_count = 0
        for item in vence_hoje:
            pid = item.get("id")
            if dar_baixa(pid, item.get("tipo", "PAGAR")):
                ok_count += 1
            else:
                err_count += 1
        # Limpa cache do dia
        context.application.bot_data.pop(f"vence_hoje_{chat_id}", None)
        msg = f"✅ *{ok_count} baixa(s) registrada(s)!*"
        if err_count:
            msg += f"\n⚠️ {err_count} falha(s) — verifique os logs."
        await query.edit_message_text(msg, parse_mode="Markdown")
        return

    if acao == "cancelar":
        await query.edit_message_reply_markup(reply_markup=None)
        return


# ─── Alerta de recebimentos atrasados (Feature 6) ────────────────────────────

async def enviar_alerta_recebimentos(app, chat_id: int):
    """Envia alertas para recebimentos atrasados com botões de ação."""
    atras_rec = [i for i in atrasados(tipo="RECEBER")]
    if not atras_rec:
        return

    hoje = date.today()
    # Foca nos mais antigos primeiro (até 5)
    atras_rec = sorted(atras_rec, key=lambda x: x.get("data_vencimento", ""))[:5]

    # Salva no bot_data para os callbacks
    app.bot_data[f"atras_rec_{chat_id}"] = atras_rec

    for idx, item in enumerate(atras_rec):
        desc     = (item.get("descricao") or "?")[:40]
        v        = _valor(item)
        venc     = item.get("data_vencimento", "")
        dias_str = ""
        if venc:
            try:
                from datetime import datetime
                dias = (hoje - datetime.strptime(venc, "%Y-%m-%d").date()).days
                dias_str = f" (há {dias} dia{'s' if dias != 1 else ''})"
            except Exception:
                pass

        contato = item.get("contato")
        if isinstance(contato, dict):
            contato_nome = contato.get("nome", "")
        else:
            contato_nome = ""

        nome_exibe = contato_nome or desc

        botoes = [[
            InlineKeyboardButton("✅ Recebi agora",      callback_data=f"alerta_rec:recebi:{idx}:{chat_id}"),
            InlineKeyboardButton("📞 Contatei",          callback_data=f"alerta_rec:contatei:{idx}:{chat_id}"),
        ], [
            InlineKeyboardButton("⏳ Aguardar",          callback_data=f"alerta_rec:aguardar:{idx}:{chat_id}"),
        ]]

        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📥 *{nome_exibe}* não pagou ainda{dias_str}.\n"
                    f"Venceu em {venc} — *R$ {v:.2f}*"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes),
            )
        except Exception as e:
            print(f"[DAILY] Erro alerta recebimento idx={idx}: {e}")


async def callback_alerta_rec(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    acao    = partes[1]
    idx     = int(partes[2])
    chat_id = int(partes[3])

    atras_rec: list = context.application.bot_data.get(f"atras_rec_{chat_id}", [])
    item = atras_rec[idx] if idx < len(atras_rec) else None

    if not item:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    desc = (item.get("descricao") or "?")[:40]
    v    = _valor(item)

    if acao == "recebi":
        parcela_id = item.get("id")
        ok = dar_baixa(parcela_id, "RECEBER")
        if ok:
            await query.edit_message_text(
                f"✅ *Recebimento registrado!*\n_{desc}_\nR$ {v:.2f}",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Falha ao registrar. Verifique os logs.")

    elif acao == "contatei":
        await query.edit_message_text(
            f"📞 *Contato registrado.*\n_{desc}_ — R$ {v:.2f}\n"
            f"_Avise quando receber para dar baixa._",
            parse_mode="Markdown",
        )

    elif acao == "aguardar":
        await query.edit_message_reply_markup(reply_markup=None)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _vencimentos_hoje() -> list:
    """Retorna parcelas a pagar com vencimento exatamente hoje."""
    hoje = str(date.today())
    from consulta_financeira import _buscar
    p = {
        "data_vencimento_de":  hoje,
        "data_vencimento_ate": hoje,
        "status":              ["EM_ABERTO", "ATRASADO"],
    }
    pagar   = [{"tipo": "PAGAR",   **i} for i in _buscar("contas-a-pagar/buscar",   p)]
    receber = [{"tipo": "RECEBER", **i} for i in _buscar("contas-a-receber/buscar", p)]
    return pagar + receber


def _saudacao() -> str:
    hora = __import__("datetime").datetime.now().hour
    if hora < 12:
        return "☀️ Bom dia!"
    if hora < 18:
        return "🌤️ Boa tarde!"
    return "🌙 Boa noite!"

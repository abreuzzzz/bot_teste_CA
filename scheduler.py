import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date


def _esc(texto: str) -> str:
    """Escapa caracteres especiais do Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(texto))


def iniciar(app, chat_id: int):
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        _relatorio_diario,
        trigger="cron",
        hour=8,
        minute=0,
        args=[app, chat_id],
    )
    scheduler.start()
    print("[SCHEDULER] Relatório diário agendado 08:00 BRT.")


async def _relatorio_diario(app, chat_id: int):
    from consulta_financeira import resumo_mes, pendentes, atrasados

    hoje   = date.today()
    resumo = resumo_mes()
    pend   = pendentes(dias=7)
    atras  = atrasados()

    # ── Linhas de pendentes ───────────────────────────────────────────────────
    if pend:
        linhas_pend = "\n".join(
            f"  {'📥' if i['tipo'] == 'RECEBER' else '📤'} "
            f"{_esc(i.get('descricao', '?')[:30])} — "
            f"R$ {_esc(f\"{i.get('valor', 0):.2f}\")} "
            f"\\({_esc(i.get('data_vencimento', ''))}\\)"
            for i in pend[:5]
        )
    else:
        linhas_pend = "  _\\(nenhum\\)_"

    # ── Linhas de atrasados ───────────────────────────────────────────────────
    if atras:
        linhas_atras = "\n".join(
            f"  ⚠️ {_esc(i.get('descricao', '?')[:30])} — "
            f"R$ {_esc(f\"{i.get('valor', 0):.2f}\")} "
            f"\\({_esc(i.get('data_vencimento', ''))}\\)"
            for i in atras[:5]
        )
    else:
        linhas_atras = "  _\\(nenhum\\)_"

    # ── Alerta saldo negativo ─────────────────────────────────────────────────
    alerta_saldo = ""
    if resumo["saldo_projetado"] < 0:
        alerta_saldo = (
            f"\n⚠️ *ALERTA: Saldo projetado negativo\\!* "
            f"R$ {_esc(f\"{resumo['saldo_projetado']:.2f}\")}\n"
        )

    # ── Monta mensagem ────────────────────────────────────────────────────────
    msg = (
        f"☀️ *Bom dia\\! Relatório de {_esc(hoje.strftime('%d/%m/%Y'))}*\n\n"
        f"📊 *Mês atual \\({_esc(resumo['periodo'])}\\):*\n"
        f"  📥 A receber: R$ {_esc(f\"{resumo['total_receber']:.2f}\")}\n"
        f"  📤 A pagar:   R$ {_esc(f\"{resumo['total_pagar']:.2f}\")}\n"
        f"  ✅ Recebido:  R$ {_esc(f\"{resumo['recebido']:.2f}\")}\n"
        f"  ✅ Pago:      R$ {_esc(f\"{resumo['pago']:.2f}\")}\n"
        f"  💰 Resultado: R$ {_esc(f\"{resumo['resultado']:.2f}\")}\n"
        f"{alerta_saldo}\n"
        f"📅 *Próximos 7 dias:*\n{linhas_pend}\n\n"
        f"🚨 *Atrasados:*\n{linhas_atras}"
    )

    # ── Envia ─────────────────────────────────────────────────────────────────
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode="MarkdownV2",
        )
        print(f"[SCHEDULER] Relatório enviado para chat_id={chat_id}.")
    except Exception as e:
        print(f"[SCHEDULER] Erro ao enviar relatório: {e}")
        # Fallback sem markdown se der erro de parse
        try:
            msg_plain = (
                f"Bom dia! Relatório de {hoje.strftime('%d/%m/%Y')}\n\n"
                f"Mês atual ({resumo['periodo']}):\n"
                f"  A receber: R$ {resumo['total_receber']:.2f}\n"
                f"  A pagar:   R$ {resumo['total_pagar']:.2f}\n"
                f"  Recebido:  R$ {resumo['recebido']:.2f}\n"
                f"  Pago:      R$ {resumo['pago']:.2f}\n"
                f"  Resultado: R$ {resumo['resultado']:.2f}\n\n"
                f"Pendentes 7 dias: {len(pend)}\n"
                f"Atrasados: {len(atras)}"
            )
            await app.bot.send_message(chat_id=chat_id, text=msg_plain)
            print("[SCHEDULER] Relatório enviado em modo plain text (fallback).")
        except Exception as e2:
            print(f"[SCHEDULER] Falha total ao enviar relatório: {e2}")

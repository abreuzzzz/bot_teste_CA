import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date


def _esc(texto: str) -> str:
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

    # ── Pendentes ─────────────────────────────────────────────────────────────
    if pend:
        linhas_pend_list = []
        for i in pend[:5]:
            emoji = "📥" if i["tipo"] == "RECEBER" else "📤"
            desc  = _esc(i.get("descricao", "?")[:30])
            valor = _esc("{:.2f}".format(i.get("valor", 0)))
            venc  = _esc(i.get("data_vencimento", ""))
            linhas_pend_list.append(f"  {emoji} {desc} — R$ {valor} \\({venc}\\)")
        linhas_pend = "\n".join(linhas_pend_list)
    else:
        linhas_pend = "  _\\(nenhum\\)_"

    # ── Atrasados ─────────────────────────────────────────────────────────────
    if atras:
        linhas_atras_list = []
        for i in atras[:5]:
            desc  = _esc(i.get("descricao", "?")[:30])
            valor = _esc("{:.2f}".format(i.get("valor", 0)))
            venc  = _esc(i.get("data_vencimento", ""))
            linhas_atras_list.append(f"  ⚠️ {desc} — R$ {valor} \\({venc}\\)")
        linhas_atras = "\n".join(linhas_atras_list)
    else:
        linhas_atras = "  _\\(nenhum\\)_"

    # ── Alerta saldo negativo ─────────────────────────────────────────────────
    alerta_saldo = ""
    if resumo["saldo_projetado"] < 0:
        saldo_fmt    = _esc("{:.2f}".format(resumo["saldo_projetado"]))
        alerta_saldo = f"\n⚠️ *ALERTA: Saldo projetado negativo\\!* R$ {saldo_fmt}\n"

    # ── Monta mensagem ────────────────────────────────────────────────────────
    hoje_fmt     = _esc(hoje.strftime("%d/%m/%Y"))
    periodo      = _esc(resumo["periodo"])
    total_rec    = _esc("{:.2f}".format(resumo["total_receber"]))
    total_pag    = _esc("{:.2f}".format(resumo["total_pagar"]))
    recebido     = _esc("{:.2f}".format(resumo["recebido"]))
    pago         = _esc("{:.2f}".format(resumo["pago"]))
    resultado    = _esc("{:.2f}".format(resumo["resultado"]))

    msg = (
        f"☀️ *Bom dia\\! Relatório de {hoje_fmt}*\n\n"
        f"📊 *Mês atual \\({periodo}\\):*\n"
        f"  📥 A receber: R$ {total_rec}\n"
        f"  📤 A pagar:   R$ {total_pag}\n"
        f"  ✅ Recebido:  R$ {recebido}\n"
        f"  ✅ Pago:      R$ {pago}\n"
        f"  💰 Resultado: R$ {resultado}\n"
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
            print("[SCHEDULER] Relatório enviado em plain text (fallback).")
        except Exception as e2:
            print(f"[SCHEDULER] Falha total: {e2}")

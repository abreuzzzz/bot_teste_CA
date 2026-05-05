"""Parser de XML de NF-e para extração de dados de lançamento."""
import xml.etree.ElementTree as ET
from datetime import datetime


# Namespace padrão NF-e
_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def _txt(elem, path: str, ns: dict) -> str:
    """Extrai texto de um subelemento, retorna '' se não encontrado."""
    e = elem.find(path, ns)
    return (e.text or "").strip() if e is not None else ""


def parse_nfe(xml_bytes: bytes) -> dict | None:
    """
    Lê um XML de NF-e e retorna dict com dados do lançamento:
    {titulo, valor, vencimento, emitente, cnpj_emitente, natureza, numero_nf}
    Retorna None se não for XML de NF-e válido.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    # Suporta raiz <nfeProc> ou <NFe> diretamente
    nfe = (root.find("nfe:NFe", _NS)
           or root.find("nfe:nfeProc/nfe:NFe", _NS)
           or (root if root.tag.endswith("NFe") else None))
    if nfe is None:
        # Tenta sem namespace
        nfe = root.find(".//NFe") or root

    infNFe = (nfe.find("nfe:infNFe", _NS)
              or nfe.find(".//infNFe"))
    if infNFe is None:
        return None

    # Emitente
    emit      = infNFe.find("nfe:emit", _NS) or infNFe.find("emit")
    emitente  = ""
    cnpj      = ""
    if emit is not None:
        emitente = (_txt(emit, "nfe:xNome", _NS) or _txt(emit, "xNome", {}))
        cnpj     = (_txt(emit, "nfe:CNPJ",  _NS) or _txt(emit, "CNPJ",  {}))

    # Ide (dados gerais da NF)
    ide     = infNFe.find("nfe:ide", _NS) or infNFe.find("ide")
    numero  = ""
    nat_op  = ""
    dhEmit  = ""
    if ide is not None:
        numero  = (_txt(ide, "nfe:nNF",   _NS) or _txt(ide, "nNF",   {}))
        nat_op  = (_txt(ide, "nfe:natOp", _NS) or _txt(ide, "natOp", {}))
        dhEmit  = (_txt(ide, "nfe:dhEmi", _NS) or _txt(ide, "dhEmi", {}))

    # Valor total
    total  = infNFe.find("nfe:total/nfe:ICMSTot", _NS) or infNFe.find(".//ICMSTot")
    valor  = 0.0
    if total is not None:
        v_str = (_txt(total, "nfe:vNF", _NS) or _txt(total, "vNF", {}))
        try:
            valor = float(v_str)
        except ValueError:
            pass

    # Data de emissão → vencimento (padrão = data de emissão)
    vencimento = str(datetime.today().date())
    if dhEmit:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(dhEmit[:19], fmt[:len(dhEmit[:19])])
                vencimento = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Duplicatas (vencimentos reais, se existirem)
    cobr  = infNFe.find("nfe:cobr", _NS) or infNFe.find("cobr")
    dups  = []
    if cobr is not None:
        for dup in (cobr.findall("nfe:dup", _NS) or cobr.findall("dup")):
            d_venc  = (_txt(dup, "nfe:dVenc", _NS) or _txt(dup, "dVenc", {}))
            d_valor = (_txt(dup, "nfe:vDup",  _NS) or _txt(dup, "vDup",  {}))
            try:
                dups.append({"vencimento": d_venc, "valor": float(d_valor)})
            except ValueError:
                pass

    titulo = nat_op or f"NF-e {numero}"
    if emitente:
        titulo = f"{nat_op or 'NF-e'} — {emitente}"

    return {
        "acao":       "PAGAR",
        "titulo":     titulo[:80],
        "valor":      valor,
        "vencimento": vencimento,
        "parcelas":   max(len(dups), 1),
        "emitente":   emitente,
        "cnpj":       cnpj,
        "numero_nf":  numero,
        "nat_op":     nat_op,
        "duplicatas": dups,   # lista de {vencimento, valor} para parcelas
    }

#!/usr/bin/env python3
"""Monitor de passagens CNF/GRU -> Turquia (ida e volta, 15 dias).

Consulta o Google Flights (via biblioteca não oficial fast-flights), converte os
preços para reais, guarda o histórico em historico.json e avisa pelo Telegram
quando o preço cai.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fast_flights import FlightData, Passengers, get_flights

# ---------------------------- CONFIGURAÇÃO ----------------------------
ORIGENS = ["CNF", "GRU"]
DESTINOS = ["IST", "SAW"]            # Istambul (aeroporto principal e Sabiha Gökçen)
PRIMEIRA_IDA = date(2027, 1, 8)
ULTIMA_IDA = date(2027, 1, 15)
DIAS_NA_VIAGEM = 15                  # volta = ida + 15 dias
ADULTOS = 2                          # AJUSTE para o número real de passageiros
CRIANCAS = 0
MAX_ESCALAS = 2                      # None = sem filtro
LIMITE_ALERTA = None                 # em R$, ex.: 15000 -> avisa sempre que ficar abaixo disso
QUEDA_MINIMA_PCT = 5                 # avisa se cair 5% ou mais vs. última execução
PAUSA_ENTRE_BUSCAS = 3               # segundos, para não sobrecarregar o Google
HISTORICO = Path(__file__).with_name("historico.json")

AEROPORTOS = {
    "CNF": "Confins",
    "GRU": "Guarulhos",
    "IST": "Istambul",
    "SAW": "Istambul (Sabiha Gökçen)",
}
SIMBOLOS = {"BRL": "R$", "USD": "US$", "EUR": "€"}
MEDALHAS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
# -----------------------------------------------------------------------


# ------------------------------ PREÇOS ---------------------------------
def para_numero(texto):
    """Converte 'R$ 4.500' ou '$1,234' em inteiro (ignora centavos)."""
    if not texto:
        return None
    texto = re.sub(r"[.,]\d{1,2}$", "", texto.strip())
    digitos = re.sub(r"\D", "", texto)
    return int(digitos) if digitos else None


def detectar_moeda(texto):
    t = (texto or "").upper()
    if "R$" in t or "BRL" in t:
        return "BRL"
    if "€" in t or "EUR" in t:
        return "EUR"
    return "USD"  # "$" ou "US$"


def _json_da_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "radar-passagens/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


_COTACOES = {}


def cotacao_para_brl(moeda):
    """Quanto vale 1 unidade da moeda em reais (None se não conseguir)."""
    if moeda == "BRL":
        return 1.0
    if moeda in _COTACOES:
        return _COTACOES[moeda]
    taxa = None
    try:
        dados = _json_da_url(f"https://economia.awesomeapi.com.br/json/last/{moeda}-BRL")
        taxa = float(dados[f"{moeda}BRL"]["bid"])
    except Exception as erro:
        print(f"  ! cotação (AwesomeAPI) falhou: {erro}")
    if taxa is None:
        try:
            dados = _json_da_url(f"https://open.er-api.com/v6/latest/{moeda}")
            taxa = float(dados["rates"]["BRL"])
        except Exception as erro:
            print(f"  ! cotação (open.er-api) falhou: {erro}")
    _COTACOES[moeda] = taxa
    return taxa


def fmt_preco(valor, moeda="BRL"):
    texto = f"{valor:,.0f}".replace(",", ".")
    return f"{SIMBOLOS.get(moeda, moeda)} {texto}"


def fmt_data(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m")


def fmt_duracao(texto):
    if not texto:
        return "—"
    m = re.search(r"(\d+)\s*hr(?:\s*(\d+)\s*min)?", texto)
    if m:
        return f"{m.group(1)}h{int(m.group(2) or 0):02d}"
    m = re.search(r"(\d+)\s*min", texto)
    return f"{m.group(1)}min" if m else texto


def fmt_escalas(n, curto=False):
    if not isinstance(n, int):
        return "—"
    if n == 0:
        return "direto"
    if curto:
        return f"{n} esc."
    return "1 escala" if n == 1 else f"{n} escalas"


def nome_aeroporto(codigo):
    return AEROPORTOS.get(codigo, codigo)


# ------------------------------- BUSCA ---------------------------------
def link_busca(origem, destino, ida, volta):
    q = f"Flights from {origem} to {destino} on {ida} through {volta}"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def buscar(origem, destino, ida, volta):
    """Retorna a opção mais barata para a combinação, ou None."""
    resultado = None
    for tentativa in range(3):
        try:
            resultado = get_flights(
                flight_data=[
                    FlightData(date=ida.isoformat(), from_airport=origem, to_airport=destino),
                    FlightData(date=volta.isoformat(), from_airport=destino, to_airport=origem),
                ],
                trip="round-trip",
                seat="economy",
                passengers=Passengers(
                    adults=ADULTOS, children=CRIANCAS, infants_in_seat=0, infants_on_lap=0
                ),
                fetch_mode="fallback",
            )
            break
        except Exception as erro:  # a lib é não oficial: falhas acontecem
            print(f"  ! {origem}->{destino} {ida}: tentativa {tentativa + 1} falhou ({erro})")
            time.sleep(5 * (tentativa + 1))
    if resultado is None:
        return None

    opcoes = []
    for voo in resultado.flights:
        preco = para_numero(voo.price)
        if preco is None:
            continue
        if MAX_ESCALAS is not None and isinstance(voo.stops, int) and voo.stops > MAX_ESCALAS:
            continue
        opcoes.append((preco, voo))
    if not opcoes:
        return None

    preco, voo = min(opcoes, key=lambda x: x[0])
    return {
        "origem": origem,
        "destino": destino,
        "ida": ida.isoformat(),
        "volta": volta.isoformat(),
        "preco": preco,
        "moeda": detectar_moeda(voo.price),
        "preco_texto": voo.price,
        "companhia": voo.name,
        "escalas": voo.stops,
        "duracao": voo.duration,
        "link": link_busca(origem, destino, ida, volta),
    }


def converter_para_reais(resultados):
    """Converte os preços para R$ (mantém o valor original em preco_original)."""
    for r in resultados:
        taxa = cotacao_para_brl(r["moeda"])
        r["preco_original"] = r["preco"]
        r["moeda_original"] = r["moeda"]
        if taxa:
            r["preco"] = round(r["preco"] * taxa)
            r["moeda"] = "BRL"
            r["cotacao"] = None if r["moeda_original"] == "BRL" else round(taxa, 4)
        else:
            r["cotacao"] = None  # sem cotação: mantém na moeda original


# ------------------------------ TELEGRAM -------------------------------
def montar_mensagem(resultados, motivos, ultimo, minimo):
    melhor = resultados[0]
    moeda = melhor["moeda"]
    e = html.escape

    linhas = ["✈️ <b>Radar de passagens · Turquia</b>", ""]
    linhas.append("🔔 <i>" + e(" · ".join(motivos)) + "</i>")
    linhas += [
        "",
        f"🏆 <b>{fmt_preco(melhor['preco'], moeda)}</b>",
        f"📍 {e(nome_aeroporto(melhor['origem']))} → {e(nome_aeroporto(melhor['destino']))}",
        f"📅 {fmt_data(melhor['ida'])} → {fmt_data(melhor['volta'])} · {DIAS_NA_VIAGEM} dias",
        f"🛫 {e(melhor['companhia'] or '—')}",
        f"⏱ {fmt_escalas(melhor['escalas'])} · {fmt_duracao(melhor['duracao'])}",
    ]

    tendencia = []
    if ultimo:
        var = (melhor["preco"] - ultimo) / ultimo * 100
        if abs(var) < 0.5:
            tendencia.append(f"➖ Igual à última consulta ({fmt_preco(ultimo, moeda)})")
        else:
            seta = "📉" if var < 0 else "📈"
            sinal = "−" if var < 0 else "+"
            tendencia.append(
                f"{seta} {sinal}{abs(var):.0f}% vs. última consulta ({fmt_preco(ultimo, moeda)})"
            )
    if minimo:
        tendencia.append(f"🏷 Menor preço já visto: {fmt_preco(min(minimo, melhor['preco']), moeda)}")
    if tendencia:
        linhas += [""] + tendencia

    if len(resultados) > 1:
        linhas += ["", "<b>Outras boas opções</b>"]
        for i, r in enumerate(resultados[1:5], 1):
            linhas.append(
                f"{MEDALHAS[i]} <b>{fmt_preco(r['preco'], r['moeda'])}</b> · "
                f"{r['origem']}→{r['destino']} · {fmt_data(r['ida'])}–{fmt_data(r['volta'])} · "
                f"{fmt_escalas(r['escalas'], curto=True)} · {fmt_duracao(r['duracao'])}"
            )

    linhas.append("")
    if melhor.get("cotacao"):
        simbolo = SIMBOLOS.get(melhor["moeda_original"], melhor["moeda_original"])
        taxa = f"{melhor['cotacao']:.2f}".replace(".", ",")
        linhas.append(f"💱 Convertido de {simbolo} a R$ {taxa} (valor aproximado)")
    linhas.append("<i>Valores ida e volta, como exibidos no Google Flights. Reconfirme antes de comprar.</i>")
    return "\n".join(linhas)


def montar_botoes(resultados):
    botoes = []
    for i, r in enumerate(resultados[:3]):
        rotulo = f"{MEDALHAS[i]} {r['origem']}→{r['destino']} · {fmt_data(r['ida'])}"
        botoes.append([{"text": f"🔎 {rotulo}", "url": r["link"]}])
    return {"inline_keyboard": botoes}


def enviar_telegram(mensagem, botoes=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("\n[Telegram não configurado] Mensagem:\n" + mensagem)
        return
    campos = {
        "chat_id": chat_id,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if botoes:
        campos["reply_markup"] = json.dumps(botoes)
    dados = urllib.parse.urlencode(campos).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dados, timeout=30
        )
        print("Mensagem enviada ao Telegram.")
    except urllib.error.HTTPError as erro:
        corpo = erro.read().decode("utf-8", "ignore")
        print(f"Falha ao enviar ao Telegram: {erro.code} {corpo}")
        print("\nMensagem que seria enviada:\n" + mensagem)


# ------------------------------ HISTÓRICO ------------------------------
def carregar_historico():
    if HISTORICO.exists():
        return json.loads(HISTORICO.read_text(encoding="utf-8"))
    return {"execucoes": []}


def main():
    resultados = []
    ida = PRIMEIRA_IDA
    while ida <= ULTIMA_IDA:
        volta = ida + timedelta(days=DIAS_NA_VIAGEM)
        for origem in ORIGENS:
            for destino in DESTINOS:
                print(f"Buscando {origem}->{destino} {ida} / {volta}")
                achado = buscar(origem, destino, ida, volta)
                if achado:
                    resultados.append(achado)
                time.sleep(PAUSA_ENTRE_BUSCAS)
        ida += timedelta(days=1)

    if not resultados:
        print("Nenhum resultado obtido nesta execução.")
        return

    converter_para_reais(resultados)
    resultados.sort(key=lambda r: r["preco"])
    melhor = resultados[0]

    # compara só com execuções na mesma moeda (o histórico antigo estava em dólar)
    historico = carregar_historico()
    anteriores = [
        e["melhor"]["preco"]
        for e in historico["execucoes"]
        if e["melhor"].get("moeda") == melhor["moeda"]
    ]
    ultimo = anteriores[-1] if anteriores else None
    minimo = min(anteriores) if anteriores else None

    motivos = []
    if not anteriores:
        motivos.append("Primeira consulta: este é o preço de referência")
    if LIMITE_ALERTA is not None and melhor["moeda"] == "BRL" and melhor["preco"] <= LIMITE_ALERTA:
        motivos.append(f"Abaixo do seu limite de {fmt_preco(LIMITE_ALERTA)}")
    if minimo is not None and melhor["preco"] < minimo:
        motivos.append("Novo menor preço já registrado")
    if ultimo and melhor["preco"] <= ultimo * (1 - QUEDA_MINIMA_PCT / 100):
        queda = (1 - melhor["preco"] / ultimo) * 100
        motivos.append(f"Queda de {queda:.0f}% desde a última consulta")

    historico["execucoes"].append(
        {
            "data": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "melhor": melhor,
            "top5": resultados[:5],
        }
    )
    historico["execucoes"] = historico["execucoes"][-200:]
    HISTORICO.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")

    if motivos:
        enviar_telegram(montar_mensagem(resultados, motivos, ultimo, minimo), montar_botoes(resultados))
    else:
        print(
            f"Sem novidades. Melhor preço agora: {fmt_preco(melhor['preco'], melhor['moeda'])} "
            f"({melhor['origem']}->{melhor['destino']})."
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Monitor de passagens CNF/GRU -> Turquia (ida e volta, 15 dias).

Consulta o Google Flights (via biblioteca não oficial fast-flights), guarda o
histórico em historico.json e avisa pelo Telegram quando o preço cai.
"""
import json
import os
import re
import time
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
LIMITE_ALERTA = None                 # ex.: 4500 -> avisa sempre que ficar abaixo disso
QUEDA_MINIMA_PCT = 5                 # avisa se cair 5% ou mais vs. última execução
PAUSA_ENTRE_BUSCAS = 3               # segundos, para não sobrecarregar o Google
HISTORICO = Path(__file__).with_name("historico.json")
# -----------------------------------------------------------------------


def para_numero(texto):
    """Converte 'R$ 4.500' ou '$1,234' em inteiro (ignora centavos)."""
    if not texto:
        return None
    texto = re.sub(r"[.,]\d{1,2}$", "", texto.strip())
    digitos = re.sub(r"\D", "", texto)
    return int(digitos) if digitos else None


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
        "preco_texto": voo.price,
        "companhia": voo.name,
        "escalas": voo.stops,
        "duracao": voo.duration,
        "link": link_busca(origem, destino, ida, volta),
    }


def enviar_telegram(mensagem):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("\n[Telegram não configurado] Mensagem:\n" + mensagem)
        return
    dados = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": mensagem, "disable_web_page_preview": "true"}
    ).encode()
    urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/sendMessage", data=dados, timeout=30
    )


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

    resultados.sort(key=lambda r: r["preco"])
    melhor = resultados[0]

    historico = carregar_historico()
    anteriores = [e["melhor"]["preco"] for e in historico["execucoes"]]
    ultimo = anteriores[-1] if anteriores else None
    minimo = min(anteriores) if anteriores else None

    motivos = []
    if not anteriores:
        motivos.append("primeira consulta (preço de referência)")
    if LIMITE_ALERTA is not None and melhor["preco"] <= LIMITE_ALERTA:
        motivos.append(f"abaixo do seu limite de {LIMITE_ALERTA}")
    if minimo is not None and melhor["preco"] < minimo:
        motivos.append("novo menor preço já registrado")
    if ultimo and melhor["preco"] <= ultimo * (1 - QUEDA_MINIMA_PCT / 100):
        queda = (1 - melhor["preco"] / ultimo) * 100
        motivos.append(f"queda de {queda:.0f}% desde a última consulta")

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
        linhas = ["✈️ Passagens para a Turquia", "Motivo: " + "; ".join(motivos), ""]
        for i, r in enumerate(resultados[:5], 1):
            linhas.append(
                f"{i}. {r['preco_texto']} | {r['origem']}->{r['destino']} | "
                f"{r['ida']} a {r['volta']} | {r['companhia']} | "
                f"{r['escalas']} escala(s) | {r['duracao']}"
            )
        linhas += ["", "Ver no Google Flights:", melhor["link"]]
        linhas += ["", "Preço por pessoa, ida e volta, como exibido pelo Google. Reconfirme antes de comprar."]
        enviar_telegram("\n".join(linhas))
    else:
        print(f"Sem novidades. Melhor preço agora: {melhor['preco_texto']} ({melhor['origem']}->{melhor['destino']}).")


if __name__ == "__main__":
    main()

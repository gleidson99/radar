#!/usr/bin/env python3
"""Monitor de passagens CNF/GRU -> Tbilisi, Geórgia (ida e volta, 15 a 20 dias).

Consulta o Google Flights (via biblioteca não oficial fast-flights), converte os
preços para reais, guarda o histórico em historico.json e avisa pelo Telegram
quando o preço cai.
"""
import asyncio
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
DESTINOS = ["TBS"]                   # Tbilisi, Geórgia
IDA_DE = date(2027, 1, 8)            # primeira data de ida a considerar
IDA_ATE = date(2027, 1, 31)          # última data de ida (a volta pode cair em fevereiro)
ESTADIA_MIN = 15                     # dias fora, no mínimo
ESTADIA_MAX = 20                     # dias fora, no máximo
# Busca em duas fases, para não fazer centenas de consultas por rodada:
PASSO_IDA_AMOSTRA = 3                # fase 1: testa uma data de ida a cada 3 dias
ESTADIAS_AMOSTRA = (15, 17, 20)      # fase 1: e só estas durações de estadia
MELHORES_PARA_REFINAR = 2            # fase 2: detalha ao redor dos 2 melhores (±1 dia, todas as estadias)
MAX_BUSCAS = 100                     # limite de consultas por rodada
ADULTOS = 2
CRIANCAS = 1                         # criança de 6 anos (faixa de 2 a 11 anos)
MAX_ESCALAS = 2                      # None = sem filtro
LIMITE_ALERTA = None                 # em R$, ex.: 15000 -> avisa sempre que ficar abaixo disso
CUSTO_TRECHO_ATE_GRU = 250           # R$ por pessoa, por trecho, de Confins até Guarulhos (ida e volta = 2 trechos)
QUEDA_MINIMA_PCT = 5                 # avisa se cair 5% ou mais vs. última execução
PAUSA_ENTRE_BUSCAS = 3               # segundos, para não sobrecarregar o Google
HISTORICO = Path(__file__).with_name("historico.json")
MILHAS = Path(__file__).with_name("milhas.json")

AEROPORTOS = {
    "CNF": "Confins",
    "GRU": "Guarulhos",
    "IST": "Istambul",
    "SAW": "Istambul (Sabiha Gökçen)",
    "TBS": "Tbilisi",
}
SIMBOLOS = {"BRL": "R$", "USD": "US$", "EUR": "€"}
MEDALHAS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
# -----------------------------------------------------------------------


# ------------------- NAVEGADOR LOCAL (substitui o da biblioteca) -------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _baixar_pagina(url):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        navegador = await p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )
        try:
            contexto = await navegador.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1366, "height": 900},
            )
            pagina = await contexto.new_page()
            await pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
            if "consent.google.com" in pagina.url:
                for rotulo in ("Accept all", "Aceitar tudo", "Reject all", "Rejeitar tudo"):
                    botao = pagina.get_by_role("button", name=rotulo)
                    if await botao.count():
                        await botao.first.click()
                        break
            try:
                await pagina.locator(".eQ35Ce").first.wait_for(state="visible", timeout=60000)
            except Exception:
                try:
                    corpo = (await pagina.inner_text("body"))[:1500].replace("\n", " | ")
                except Exception:
                    corpo = "?"
                print(f"  ? página recebida: título={await pagina.title()!r} url={pagina.url[:120]!r}")
                print(f"  ? texto: {corpo}")
                raise RuntimeError("a página de resultados do Google não carregou")
            return await pagina.evaluate("document.querySelector('[role=\"main\"]').innerHTML")
        finally:
            await navegador.close()


def navegador_local(params):
    url = "https://www.google.com/travel/flights?" + "&".join(f"{k}={v}" for k, v in params.items())
    corpo = asyncio.run(_baixar_pagina(url))

    class Resposta:
        status_code = 200
        text = corpo
        text_markdown = corpo

    return Resposta


try:
    import fast_flights.local_playwright as _lp

    _lp.local_playwright_fetch = navegador_local
except Exception as _erro:  # se a biblioteca mudar, cai no comportamento padrão
    print(f"(não foi possível trocar o navegador local: {_erro})")


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


def fmt_num(valor):
    return f"{valor:,.0f}".replace(",", ".")


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


_CRIANCA_COMO_ADULTO = False  # vira True se só a busca com 3 adultos funcionar


def _variantes():
    base = (ADULTOS, CRIANCAS)
    alternativa = (ADULTOS + CRIANCAS, 0)
    if CRIANCAS == 0:
        return [base]
    return [alternativa] if _CRIANCA_COMO_ADULTO else [base, alternativa]


def buscar(origem, destino, ida, volta):
    """Retorna a opção mais barata para a combinação, ou None."""
    global _CRIANCA_COMO_ADULTO
    resultado = None
    usou = None
    for adultos, criancas in _variantes():
        for tentativa in range(2):
            try:
                resultado = get_flights(
                    flight_data=[
                        FlightData(date=ida.isoformat(), from_airport=origem, to_airport=destino),
                        FlightData(date=volta.isoformat(), from_airport=destino, to_airport=origem),
                    ],
                    trip="round-trip",
                    seat="economy",
                    passengers=Passengers(
                        adults=adultos, children=criancas, infants_in_seat=0, infants_on_lap=0
                    ),
                    fetch_mode="local",
                )
                usou = (adultos, criancas)
                break
            except Exception as erro:  # a lib é não oficial: falhas acontecem
                texto = str(erro)
                print(
                    f"  ! {origem}->{destino} {ida} [{adultos} adulto(s) + {criancas} criança(s)]: "
                    f"tentativa {tentativa + 1} falhou ({texto[:200]})"
                )
                if "turnstile" in texto.lower() or "no token" in texto.lower():
                    break
                time.sleep(5)
        if resultado is not None:
            break
    if resultado is None:
        return None
    if usou and CRIANCAS and usou[1] == 0 and not _CRIANCA_COMO_ADULTO:
        _CRIANCA_COMO_ADULTO = True
        print("  >>> só a busca com a criança contada como adulto funcionou; usando assim nas próximas")

    opcoes = []
    for voo in resultado.flights:
        preco = para_numero(voo.price)
        if not preco or preco <= 0:  # ignora linhas sem preço válido (ex.: "0")
            continue
        if MAX_ESCALAS is not None and isinstance(voo.stops, int) and voo.stops > MAX_ESCALAS:
            continue
        opcoes.append((preco, voo))
    if not opcoes:
        amostra = [(v.price, v.name, v.stops, v.duration) for v in resultado.flights[:3]]
        print(f"  ! {origem}->{destino} {ida}: sem preço válido ({len(resultado.flights)} voos). Amostra: {amostra}")
        return None

    preco, voo = min(opcoes, key=lambda x: x[0])
    return {
        "origem": origem,
        "destino": destino,
        "ida": ida.isoformat(),
        "volta": volta.isoformat(),
        "dias": (volta - ida).days,
        "preco": preco,
        "moeda": detectar_moeda(voo.price),
        "preco_texto": voo.price,
        "companhia": voo.name,
        "escalas": voo.stops,
        "duracao": voo.duration,
        "link": link_busca(origem, destino, ida, volta),
        "crianca_como_adulto": bool(CRIANCAS and usou and usou[1] == 0),
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


def aplicar_custo_ate_gru(resultados):
    """Soma o deslocamento CNF<->GRU (por pessoa) às opções que saem de Guarulhos,
    para comparar com as que saem direto de Confins em pé de igualdade."""
    extra = CUSTO_TRECHO_ATE_GRU * 2
    for r in resultados:
        r["ajuste"] = 0
        if r["origem"] == "GRU" and r["moeda"] == "BRL" and extra:
            r["preco_google"] = r["preco"]
            r["preco"] += extra
            r["ajuste"] = extra


# ------------------------------ TELEGRAM -------------------------------
def montar_mensagem(resultados, motivos, ultimo, minimo, milhas_cfg=None):
    melhor = resultados[0]
    moeda = melhor["moeda"]
    e = html.escape

    linhas = ["✈️ <b>Radar de passagens · Geórgia</b>", ""]
    linhas.append("🔔 <i>" + e(" · ".join(motivos)) + "</i>")
    linhas += [
        "",
        f"🏆 <b>{fmt_preco(melhor['preco'], moeda)}</b>",
        f"📍 {e(nome_aeroporto(melhor['origem']))} → {e(nome_aeroporto(melhor['destino']))}",
        f"📅 {fmt_data(melhor['ida'])} → {fmt_data(melhor['volta'])} · {melhor['dias']} dias",
        f"🛫 {e(melhor['companhia'] or '—')}",
        f"⏱ {fmt_escalas(melhor['escalas'])} · {fmt_duracao(melhor['duracao'])}",
    ]
    if melhor.get("ajuste"):
        linhas.append(
            f"🚌 Inclui {fmt_preco(melhor['ajuste'])} por pessoa do trecho CNF↔GRU "
            f"(Google: {fmt_preco(melhor['preco_google'])})"
        )

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
                f"{MEDALHAS[i]} <b>{fmt_preco(r['preco'], r['moeda'])}</b>{' ✚' if r.get('ajuste') else ''} · "
                f"{r['origem']}→{r['destino']} · {fmt_data(r['ida'])}–{fmt_data(r['volta'])} · "
                f"{fmt_escalas(r['escalas'], curto=True)} · {fmt_duracao(r['duracao'])}"
            )

    linhas += secao_milhas(melhor, milhas_cfg or {})

    linhas.append("")
    if melhor.get("cotacao"):
        simbolo = SIMBOLOS.get(melhor["moeda_original"], melhor["moeda_original"])
        taxa = f"{melhor['cotacao']:.2f}".replace(".", ",")
        linhas.append(f"💱 Convertido de {simbolo} a R$ {taxa} (valor aproximado)")
    if melhor.get("crianca_como_adulto"):
        linhas.append("👶 Preço calculado com 3 adultos; a criança de 6 anos costuma pagar um pouco menos")
    if any(r.get("ajuste") for r in resultados[:5]):
        linhas.append("✚ inclui o deslocamento CNF↔GRU por pessoa, ida e volta")
    linhas.append("<i>Valores ida e volta, como exibidos no Google Flights. Reconfirme antes de comprar.</i>")
    return "\n".join(linhas)


def carregar_milhas():
    """Lê milhas.json (valor do milheiro e ofertas em milhas que você encontrou)."""
    if MILHAS.exists():
        try:
            return json.loads(MILHAS.read_text(encoding="utf-8"))
        except Exception as erro:
            print(f"  ! milhas.json inválido: {erro}")
    return {}


def secao_milhas(melhor, cfg):
    """Mostra só valores reais em milhas cadastrados em milhas.json (sem estimativas)."""
    e = html.escape
    ofertas = [o for o in cfg.get("ofertas", []) if o.get("milhas")]
    if not ofertas:
        return []
    ofertas.sort(key=lambda o: o["milhas"])
    linhas = ["", "<b>✨ Milhas (valores consultados)</b>"]
    for o in ofertas[:5]:
        taxas = f" + {fmt_preco(o['taxas'])}" if o.get("taxas") else ""
        obs = f" · {e(o['obs'])}" if o.get("obs") else ""
        linhas.append(
            f"💳 {e(o.get('programa', 'Programa'))}: {fmt_num(o['milhas'])} milhas{taxas}{obs}"
        )
    return linhas


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


def diagnostico():
    """Mostra a versão da biblioteca e como ela trata o modo de busca (ajuda a achar erros)."""
    try:
        import importlib.metadata as md
        import inspect

        from fast_flights import core

        print("fast-flights", md.version("fast-flights"), "| playwright", md.version("playwright"))
        fonte = inspect.getsource(core.get_flights_from_filter)
        print("\n".join(l for l in fonte.splitlines() if "mode" in l))
    except Exception as erro:
        print(f"(diagnóstico indisponível: {erro})")


def datas_de_ida(passo=1):
    ida = IDA_DE
    while ida <= IDA_ATE:
        yield ida
        ida += timedelta(days=passo)


def main():
    diagnostico()
    cache = {}            # (origem, destino, ida, volta) -> resultado ou None
    estado = {"falhas": 0, "buscas": 0}

    def consultar(origem, destino, ida, volta):
        chave = (origem, destino, ida, volta)
        if chave in cache:
            return cache[chave]
        if estado["buscas"] >= MAX_BUSCAS:
            return None
        estado["buscas"] += 1
        print(f"[{estado['buscas']}/{MAX_BUSCAS}] Buscando {origem}->{destino} {ida} / {volta} ({(volta - ida).days} dias)")
        achado = buscar(origem, destino, ida, volta)
        cache[chave] = achado
        if achado:
            estado["falhas"] = 0
        else:
            estado["falhas"] += 1
            if estado["falhas"] >= 3 and not any(cache.values()):
                print("Abortando: 3 buscas seguidas sem resultado. Veja os erros acima.")
                raise SystemExit(1)
        time.sleep(PAUSA_ENTRE_BUSCAS)
        return achado

    # Fase 1: amostra espalhada pelo período (só Istambul principal)
    print(f"Fase 1: saídas de {IDA_DE} a {IDA_ATE}, estadias {ESTADIAS_AMOSTRA}")
    for ida in datas_de_ida(PASSO_IDA_AMOSTRA):
        for estadia in ESTADIAS_AMOSTRA:
            for origem in ORIGENS:
                consultar(origem, DESTINOS[0], ida, ida + timedelta(days=estadia))

    # Fase 2: detalha ao redor dos melhores achados
    fase1 = sorted((r for r in cache.values() if r), key=lambda r: r["preco"])
    escolhidos, vistos = [], set()
    for r in fase1:
        chave = (r["origem"], r["ida"])
        if chave not in vistos:
            vistos.add(chave)
            escolhidos.append(r)
        if len(escolhidos) >= MELHORES_PARA_REFINAR:
            break
    print(f"Fase 2: refinando ao redor de {[(r['origem'], r['ida']) for r in escolhidos]}")
    for r in escolhidos:
        ida_base = date.fromisoformat(r["ida"])
        for delta in (-1, 0, 1):
            ida = ida_base + timedelta(days=delta)
            if not (IDA_DE <= ida <= IDA_ATE):
                continue
            for estadia in range(ESTADIA_MIN, ESTADIA_MAX + 1):
                consultar(r["origem"], DESTINOS[0], ida, ida + timedelta(days=estadia))

    # Fase 3: confere os outros aeroportos de destino só nas melhores datas
    atuais = sorted((r for r in cache.values() if r), key=lambda r: r["preco"])
    for r in atuais[:MELHORES_PARA_REFINAR]:
        for destino in DESTINOS[1:]:
            consultar(r["origem"], destino, date.fromisoformat(r["ida"]), date.fromisoformat(r["volta"]))

    resultados = [r for r in cache.values() if r]
    print(f"Consultas feitas: {estado['buscas']} · com resultado: {len(resultados)}")

    if not resultados:
        print("Nenhum resultado obtido nesta execução.")
        return

    converter_para_reais(resultados)
    aplicar_custo_ate_gru(resultados)
    resultados.sort(key=lambda r: r["preco"])
    melhor = resultados[0]

    # compara só com execuções na mesma moeda (o histórico antigo estava em dólar)
    historico = carregar_historico()
    anteriores = [
        e["melhor"]["preco"]
        for e in historico["execucoes"]
        if e["melhor"].get("moeda") == melhor["moeda"] and e["melhor"].get("preco", 0) > 0
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
        enviar_telegram(
            montar_mensagem(resultados, motivos, ultimo, minimo, carregar_milhas()),
            montar_botoes(resultados),
        )
    else:
        print(
            f"Sem novidades. Melhor preço agora: {fmt_preco(melhor['preco'], melhor['moeda'])} "
            f"({melhor['origem']}->{melhor['destino']})."
        )


if __name__ == "__main__":
    main()

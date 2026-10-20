#!/usr/bin/env python3
"""Sondagem do Azul pelo Mundo: abre a página de resultados num navegador, captura a
resposta de /api/availability e imprime a estrutura. Serve para descobrir se o site
atende o servidor do GitHub e como ler os preços em pontos."""
import asyncio
import json

from playwright.async_api import async_playwright

URL = (
    "https://azulpelomundo.voeazul.com.br/flights/RT/GRU/IST/-/-/"
    "2027-01-14/2027-01-29/2/1/0/0/0/ALL/F/ECONOMY/-/-/-/-/A/-"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def forma(o, d=0):
    if o is None or not isinstance(o, (dict, list)):
        return type(o).__name__
    if isinstance(o, list):
        return [f"lista[{len(o)}]", forma(o[0], d + 1) if o and d < 6 else None]
    if d > 6:
        return "{...}"
    return {k: forma(v, d + 1) for k, v in list(o.items())[:30]}


async def main():
    capturas = []
    async with async_playwright() as p:
        navegador = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        contexto = await navegador.new_context(
            user_agent=USER_AGENT, locale="pt-BR", timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 900},
        )
        pagina = await contexto.new_page()

        async def ao_responder(resp):
            if "/api/availability" in resp.url:
                try:
                    corpo = await resp.text()
                except Exception as erro:
                    corpo = f"<erro ao ler: {erro}>"
                capturas.append((resp.status, resp.headers.get("content-type"), corpo))

        pagina.on("response", lambda r: asyncio.create_task(ao_responder(r)))
        print("Abrindo a página de resultados...")
        try:
            await pagina.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as erro:
            print(f"! falha ao abrir: {erro}")
        for _ in range(45):
            if capturas:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(3)
        print("Título:", await pagina.title())
        texto = (await pagina.inner_text("body"))[:1500].replace("\n", " | ")
        print("Texto visível:", texto)
        await navegador.close()

    if not capturas:
        print("RESULTADO: nenhuma resposta de /api/availability (site bloqueou ou não carregou)")
        return
    for status, tipo, corpo in capturas:
        print(f"\nRESULTADO: status {status} · {tipo} · {len(corpo)} caracteres")
        try:
            dados = json.loads(corpo)
        except Exception:
            print("Corpo (não é JSON):", corpo[:800])
            continue
        print("ESTRUTURA:", json.dumps(forma(dados), ensure_ascii=False, indent=1)[:4000])
        print("AMOSTRA:", json.dumps(dados, ensure_ascii=False)[:6000])


asyncio.run(main())

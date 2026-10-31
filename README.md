# Radar de passagens (CNF/GRU → Tbilisi e Istambul)

Monitor em Python que consulta preços do Google Flights e avisa no Telegram.

## Modo GitHub (recomendado): API do SerpApi
O Google bloqueia acesso automatizado, então no GitHub o monitor usa o **SerpApi**, que entrega os resultados do Google Flights por API. O plano grátis dá **250 buscas por mês**.

- Roda **a cada 6 horas** (23:17, 05:17, 11:17 e 17:17, horário de Brasília), com **2 buscas** por execução (~248/mês).
- Origem **Confins (CNF)**; destinos **Tbilisi (TBS)** e **Istambul (IST e SAW)**, todos na mesma busca.
- Ida de **01 a 15/jan**, estadia de **15 a 25 dias** (testa 15, 17, 19, 21, 23 e 25). O rodízio cobre as 90 combinações em ~15 dias e, 1x por dia, reconfere a data mais barata.
- Guarda o último preço de cada combinação (até 20 dias) e compara sempre com o melhor já conhecido.
- Manda **1 resumo por dia** e avisa a qualquer hora se surgir novo menor preço ou queda de 5% ou mais.
- Evite rodar manualmente: a cota grátis fica quase toda usada pelos agendamentos.

### Configuração
1. Crie uma conta grátis em serpapi.com e copie a sua **API Key** (menu "Api Key").
2. No GitHub: Settings → Secrets and variables → Actions → New repository secret:
   `SERPAPI_KEY` = sua chave. (`TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` continuam como estão.)
3. Em Actions → Monitor de passagens → Run workflow, rode uma vez para testar.

Ajustes no início de `monitor_passagens.py` (datas, estadias, passageiros) e `BUSCAS_SERPAPI` (buscas por execução).

## Modo local (Windows) — não funciona mais
O Google passou a recusar o Chrome automatizado. Os scripts `.bat` ficam só como referência.

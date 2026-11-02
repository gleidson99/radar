# Radar de passagens (CNF/GRU → Tbilisi e Istambul)

Monitor em Python que consulta preços do Google Flights e avisa no Telegram.

## Modo GitHub (recomendado): API do SerpApi
O Google bloqueia acesso automatizado, então no GitHub o monitor usa o **SerpApi**, que entrega os resultados do Google Flights por API. O plano grátis dá **250 buscas por mês**.

- Roda **3 vezes por dia** (06:00, 14:00 e 22:00, horário de Brasília), com **2 buscas** por execução (~186/mês).
- Origem **Confins (CNF)**; destinos **Tbilisi (TBS)** e **Istambul (IST e SAW)**, todos na mesma busca.
- Ida de **01 a 15/jan**, estadia de **19 a 24 dias** (testa todos: 19, 20, 21, 22, 23 e 24). O rodízio passa primeiro por todas as datas de ida com 21 dias (≈ 2,5 dias para cobrir o período), depois 19, 24, 23, 20 e 22; 1x por dia reconfere a data mais barata.
- Guarda o último preço de cada combinação (até 20 dias) e compara sempre com o melhor já conhecido.
- **Toda execução manda mensagem** no Telegram, com as datas consultadas, quantas das 90 combinações já têm preço e quantas buscas restam no mês.
- O GitHub costuma atrasar os horários agendados (às vezes 1 a 3 horas); isso é normal.

### Busca manual (Actions → Monitor de passagens → Run workflow)
- **buscas**: quantas consultas fazer (padrão 6). Cada uma = 1 data de ida + 1 estadia.
- **ida** (opcional): uma data específica, ex. `2027-01-05`.
- **dias** (opcional): estadias para essa data, ex. `21` ou `19,22,24`. Vazio = 19 a 24.
- Sem data, a busca manual continua o rodízio. Cuidado com a cota: o automático gasta ~186 das 250 buscas do mês.

### Configuração
1. Crie uma conta grátis em serpapi.com e copie a sua **API Key** (menu "Api Key").
2. No GitHub: Settings → Secrets and variables → Actions → New repository secret:
   `SERPAPI_KEY` = sua chave. (`TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` continuam como estão.)
3. Em Actions → Monitor de passagens → Run workflow, rode uma vez para testar.

Ajustes no início de `monitor_passagens.py` (datas, estadias, passageiros) e `BUSCAS_SERPAPI` (buscas por execução).

## Modo local (Windows) — não funciona mais
O Google passou a recusar o Chrome automatizado. Os scripts `.bat` ficam só como referência.

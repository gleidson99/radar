# Radar de passagens (CNF/GRU → Tbilisi)

Monitor em Python que consulta preços do Google Flights e avisa no Telegram.

## Modo GitHub (recomendado): API do SerpApi
O Google bloqueia acesso automatizado, então no GitHub o monitor usa o **SerpApi**, que entrega os resultados do Google Flights por API. O plano grátis dá **250 buscas por mês**.

- Roda **1x por dia** (08:17, horário de Brasília), com **8 buscas** por dia (~240/mês).
- Em cada execução, reconfere as 2 combinações mais baratas já encontradas e testa 6 novas de um rodízio
  (saídas de 08 a 31/jan, estadias de 15, 17 e 20 dias, saindo de CNF e de GRU). O rodízio cobre tudo em cerca de 3 semanas.
- Manda um resumo diário no Telegram e destaca novo menor preço ou queda de 5% ou mais.

### Configuração
1. Crie uma conta grátis em serpapi.com e copie a sua **API Key** (menu "Api Key").
2. No GitHub: Settings → Secrets and variables → Actions → New repository secret:
   `SERPAPI_KEY` = sua chave. (`TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` continuam como estão.)
3. Em Actions → Monitor de passagens → Run workflow, rode uma vez para testar.

Ajustes no início de `monitor_passagens.py` (datas, estadias, passageiros) e `BUSCAS_SERPAPI` (buscas por execução).

## Modo local (Windows) — não funciona mais
O Google passou a recusar o Chrome automatizado. Os scripts `.bat` ficam só como referência.

# Radar de passagens (CNF/GRU → Tbilisi)

Monitor em Python que consulta o Google Flights **no seu PC Windows** a cada hora e avisa no Telegram.

- **Toda hora:** reconfere as 5 melhores combinações de datas.
- **1x por dia:** varredura completa (08–31/jan, estadia de 15 a 20 dias, CNF e GRU) + resumo.
- Alerta quando há novo menor preço ou queda de 5%+. Se ficar 3 execuções sem conseguir consultar, avisa também.

## Instalação (Windows)
1. Instale o Python (python.org) marcando **Add Python to PATH**, e o Google Chrome.
2. Baixe este repositório (Code → Download ZIP) e extraia numa pasta.
3. No Prompt de Comando, dentro da pasta: `pip install -r requirements.txt`
4. Copie `segredos.exemplo.txt` para `segredos.txt` e preencha o token do bot (o arquivo fica só no seu PC).
5. Dê dois cliques em `teste_windows.bat` (abre o Chrome, faz poucas buscas e manda uma mensagem de teste).
6. Se o teste funcionou, dê dois cliques em `instalar_tarefa.bat`. Para parar: `remover_tarefa.bat`.

Logs em `log_monitor.txt`. O GitHub Actions ficou só como execução manual (o Google não atende os servidores do GitHub).

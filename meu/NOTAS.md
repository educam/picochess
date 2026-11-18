# Notas pessoais: retomada do PicoChess (18/11/2026)

## Origem
- Repositório ativo: https://github.com/JohanSjoblom/picochess (é o fork mantido do original `jromang/picochess`, que está parado desde 2023)
- Versão: **4.4.1**; último commit em 17/11/2026; cerca de 500 commits desde agosto/2026
- O clone local é raso (últimos 300 commits)

## Como rodar localmente sem tabuleiro
`./meu/run-local.sh` e depois abra http://localhost:8080
- Usa `board-type = noeboard`, a porta 8080 (a 80 exige root) e o Stockfish 19 / LC0 do pacote `engines-x86_64-small` v4.4.1
- Testado neste ambiente: a interface carrega, o lance `e4` é aceito pelo browser (`POST /channel action=move`) e o Stockfish responde `...Nc6`
- Observações do teste:
  - O engine levou cerca de 15 s para responder com tempo 5+3 (Elo@2200 e `Move Overhead = 2000`)
  - O livro de aberturas não carrega com este pacote de engines (`no opening books available`): falta rodar `install-books-games.sh`
  - Sem `sox` instalado, a voz desliga sozinha. É inofensivo
  - `location = auto` tenta geolocalizar via internet. É bom fixar uma localização ou usar `theme` diferente de `auto`

## O que já existe hoje (relevante para o meu objetivo)
| Área | Estado atual |
|---|---|
| Jogar só pelo browser | Maduro (`noeboard`), com tabuleiro chessground, relógio, análise MultiPV, Watcher/Tutor, livro e base de partidas |
| Browser + tabuleiro físico | Funciona: o browser vira display e controle e os lances vêm do e-board. Status do e-board no rodapé via websocket |
| Plataformas | Linux/Pi (principal). Windows e macOS são experimentais, focados em web-only (`install-picochess-windows.ps1`, `install-picochess-mac.sh`) |
| DGT no Windows | Via porta COM virtual do Bluetooth (`--dgt-port COM7`), sem validação em hardware |
| Boards | DGT, Certabo, ChessLink, Chessnut, iChessOne, Citrine e Saitek OSA (os dois últimos são novos, de nov/2026) |
| Configuração pelo browser | `/settings`: tabela crua de chaves do `picochess.ini` (checkbox + valor), mais abas de Wi-Fi e Bluetooth. A maioria das mudanças só vale após reiniciar |
| Menu na web | Emula o menu do relógio DGT (botões `< − ‖ + >` e um display de texto curto). O tipo de e-board pode ser trocado por ele (`action=eboard` em `server.py`) |
| Onboarding | Wi-Fi via `/onboard`, hotspot do celular, pareamento por BT (experimental) |
| Áudio | Pode sair pelo celular/browser remoto (`web-audio-backend-remote`) |
| Automação/testes | Servidor MCP em `mcp-server/` que joga e inspeciona via HTTP/WebSocket. Ótimo para testar sem tabuleiro |
| Arquitetura | Toda em `asyncio` (sem threads novas) e tipada com mypy. Regras de IA em `AGENTS.md` (leitura obrigatória antes de mexer) |

## Pontos de dor percebidos (alinhados ao meu objetivo)
1. **A configuração é um editor de .ini cru**: há cerca de 90 chaves sem agrupamento, sem descrição, sem validação e com placeholders de exemplo (smtp, remote...). Tudo exige reinício.
2. **O menu web imita o display de 8 caracteres do relógio DGT**, o que obriga a navegar como no hardware em vez de usar formulários e listas.
3. **A conexão do e-board não tem assistente**: não há descoberta de portas no browser (só Certabo e ChessLink usam `serial.tools.list_ports`), nem botão "testar conexão", nem leitura ao vivo do board na tela de setup. No Windows/Mac é preciso descobrir COMx ou `/dev/cu.*` e passar na linha de comando ou no ini.
4. **Caminhos absolutos `/opt/picochess`** aparecem nos exemplos de ini, `.uci` (SyzygyPath) e `utilities.py`. Rodar a partir de outra pasta exige `sed`.
5. **Os passos de instalação são separados** (engines, livros/jogos, serviços), sem uma checagem do tipo "o que está faltando?" na interface.

## Ideias de melhoria (para discutir/priorizar)
### A. Assistente de configuração no browser ("Setup")
- Uma página `/setup` em etapas: 1) Tabuleiro (tipo + porta detectada + botão Testar, mostrando o FEN lido ao vivo), 2) Engine e nível, 3) Tempo e cor, 4) Tutor e voz, 5) Aparência.
- Endpoint `GET /settings/ports` usando `serial.tools.list_ports.comports()` (USB/BT/COM no Linux, Mac e Windows) e BLE scan para Chessnut/iChessOne.
- Aplicar a troca de board a quente (o backend já tenta isso em `action=eboard`) e mostrar o status sem reiniciar.

### B. `/settings` agrupado e documentado
- Gerar um esquema a partir do `configuration.py` (argparse já tem `help`, `choices` e `default`) e renderizar por seções: Tabuleiro, Engine, Jogo, Tutor, Áudio, Web, Avançado.
- Esconder chaves de exemplo e não habilitadas, validar no save (já existe `check-config.py`) e indicar quais mudanças pedem reinício.

### C. Menu web "nativo"
- Manter o menu estilo relógio para fidelidade, mas oferecer um painel com listas: engines (com busca e agrupado por fabricante), modos, tempo e posição.

### D. Portabilidade / rodar de qualquer pasta
- Resolver caminhos relativos à raiz do repo (por exemplo, um `PICOCHESS_HOME`) em vez de `/opt/picochess`.
- Um `run-local` oficial (como este script) para desenvolvimento em laptop.

### E. Modo "simulador de e-board" para desenvolvimento
- Um `board-type = virtual` que aceita FENs/peças por WebSocket ou CLI, imitando o fluxo do DGT (levantar e colocar peça, set pieces, takeback físico). Permitiria testar as regras de `NEW_GAME`, takeback e Tutor "lift" sem hardware.

## Próximos passos sugeridos
- [ ] Decidir onde guardar a cópia de forma permanente (fork no meu GitHub + branch pessoal)
- [ ] Rodar `install-books-games.sh` para ter livro e base de jogos
- [ ] Rodar os testes: `venv/bin/tox -e unit`
- [ ] Escolher a primeira melhoria (sugestão: A, com descoberta de portas e teste de conexão)

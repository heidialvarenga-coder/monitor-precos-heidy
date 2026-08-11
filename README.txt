MONITOR DE PREÇOS - PROMOS DA HEIDY

O que esta primeira versão faz:
- recebe link pelo Telegram com /monitorar
- salva o preço inicial
- verifica periodicamente
- avisa no Telegram quando o preço cair
- lista produtos com /lista
- remove com /remover ID

IMPORTANTE:
1. NÃO coloque o token do Telegram neste arquivo.
2. No servidor, crie a variável de ambiente:
   TELEGRAM_BOT_TOKEN = SEU_TOKEN_NOVO
3. CHECK_MINUTES pode ser 30, 60 etc.
4. Esta primeira versão foi preparada para TESTAR links de produtos,
   começando pelo Mercado Livre. Algumas lojas podem bloquear leitura
   automática; depois adicionamos conectores específicos para cada loja.

COMANDOS:
 /start
 /ajuda
 /monitorar LINK
 /lista
 /remover ID

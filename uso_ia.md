# Uso de Inteligência Artificial

## Ferramentas utilizadas
- Claude (Anthropic), assistente de IA conversacional.

## Para que foi usada
- Estruturar o projeto (pastas, campos da base, arquitetura em Python).
- Gerar um primeiro rascunho do código de `src/sistema.py`, dos modelos de prompt (M1 e M2) e do conjunto de perguntas de teste.
- Redigir rascunhos do README e do relatório.

## O protótipo usa IA generativa?
Não. O assistente é baseado em regras, busca por palavras-chave (A) e TF-IDF (B). Os "modelos de prompt" (M1 e M2) definem papel, formato e regras da resposta; a função `montar_prompt` mostra o texto que seria enviado a um modelo externo, mas nenhum modelo externo é chamado.

## Prompts testados (exemplos)
1. M1 (direto): "Você é um assistente de orientação cidadã. Responda de forma breve. Use somente a base fornecida. Cite a fonte."
2. M2 (estruturado): papel não oficial + formato com assunto, orientação, fonte, data, aviso e relacionados + regras de não inventar e informar limites.

## Validação crítica realizada
- Executamos `python src/sistema.py --testes` e conferimos cada resultado em `docs/resultados_testes.csv`.
- As orientações da base **precisam ser conferidas pela equipe** nas fontes listadas (abrir cada link, confirmar o conteúdo e atualizar `data_verificacao`). A IA não substitui essa verificação.
- Os testes revelaram falhas reais (variações de palavras), que foram mantidas e registradas como limitação, e não escondidas.
- Revisamos o código, entendemos o fluxo (menu, busca, decisão, formatação) e conseguimos explicá-lo na apresentação.

## Responsabilidade
A equipe compreende, testou e justifica o funcionamento da solução.

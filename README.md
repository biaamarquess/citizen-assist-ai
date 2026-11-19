# Citizen Assist AI

Assistente digital (interface textual, em Python) que organiza orientações cidadãs verificadas, responde consultas simples, **cita a fonte** e **avisa quando não há resposta suficiente**.

> Protótipo educacional (Global Solution FIAP). **Não é canal oficial** de nenhum órgão público e **não coleta dados pessoais**.

- **Integrantes (RM):** [571819 - Beatriz Marques Souza]; 

## 2. Problema, público e temas
Cidadãos precisam encontrar orientações confiáveis sobre documentos, serviços e situações comuns. Quando fontes e instruções estão dispersas, a busca fica lenta e sujeita a interpretações incorretas.

- **Público beneficiado:** pessoas que buscam orientação inicial rápida e clara sobre o cotidiano cidadão.
- **Temas (3):** Documentos, Serviços e Direitos e orientações comunitárias.
- **Escopo:** 19 orientações resumidas, cada uma com fonte e data de verificação.

## 3. Base de conhecimento, estruturas e busca
**Arquivo:** `data/base.json` (JSON, UTF-8). Campos de cada registro:

| Campo | Obrigatório | Descrição |
|---|---|---|
| id | sim | Identificador único (D01, S02, C03...) |
| tema / subtema | sim | Posição na hierarquia |
| palavras_chave | sim | Lista de termos usados na busca |
| pergunta | sim | Pergunta-título do assunto |
| orientacao | sim | Orientação resumida |
| referencia | sim | Endereço (URL) da fonte consultada |
| data_verificacao | sim | AAAA-MM-DD |
| requer_confirmacao | não | Se `true`, a resposta exibe aviso para confirmar requisitos atualizados |
| relacionados | não | Ids de assuntos ligados (arestas do grafo) |

**Leitura e validação (`carregar_base`):** trata arquivo ausente, JSON inválido, base vazia, campo obrigatório ausente, data fora do formato, referência sem endereço e id duplicado. Registros inválidos são ignorados e listados na inicialização. Para **acrescentar ou corrigir orientações basta editar o JSON**, sem mexer nas regras do programa.

**Estruturas de dados:**
- *Lista de dicionários* com os registros; dicionários `por_id`, `por_tema` e `por_subtema` para recuperação direta.
- *Índice invertido* (`token -> conjunto de ids`) das palavras-chave.
- *Hierarquia* tema > subtema > orientação (menu "Ver mapa de temas e relações").
- *Grafo ponderado de assuntos:* nós = orientações; arestas com peso 1 (relacionados explícitos), 2 (mesmo subtema) e 3 (mesmo tema). O **algoritmo de Dijkstra** calcula os assuntos mais próximos, usados como sugestões de continuidade (3 opções após cada resposta).

**Estratégias de busca (comparadas nos testes):**
- **A - palavras-chave com índice invertido:** +1 ponto por termo da pergunta presente nas palavras-chave; +2 quando uma palavra-chave inteira aparece na pergunta.
- **B - TF-IDF com similaridade do cosseno** sobre o texto completo do registro.

**Várias correspondências:** se o 2º colocado tem pontuação >= 80% da do 1º, a consulta é tratada como **ambígua** e o usuário escolhe entre até 3 opções. Pontuação baixa gera pedido de confirmação ("Você quis dizer...? s/n"). Se a pessoa cita só o tema (ex.: "documentos"), o sistema lista as orientações do tema.

## 4. Regras de resposta, modelos de prompt e limitações
Condicionais tratam: entrada vazia, entrada inválida, opção inexistente, correspondência forte, fraca, ambígua e ausência de correspondência. Nunca se inventa instrução: sem base suficiente, o sistema informa o limite, lembra que não é canal oficial e oferece temas alternativos.

Dois **modelos de instrução de resposta** (definidos em `MODELOS`, em `src/sistema.py`; a função `montar_prompt` mostra o texto que seria enviado a um modelo externo):

| | M1 - Direto | M2 - Estruturado |
|---|---|---|
| Papel | Assistente de orientação cidadã, respostas breves | Assistente de orientação cidadã, não oficial, sem pedir dados pessoais |
| Formato | Orientação + fonte | Assunto, orientação, fonte, data de verificação, aviso de confirmação, aviso de não oficialidade e assuntos relacionados |
| Regras | Usar só a base; citar fonte | Usar só a base; nunca inventar; citar fonte e data; avisar para confirmar; informar limites; linguagem simples |

**Comparação:** checklist automático de 5 critérios (cita fonte, cita data, aviso de não oficialidade, aviso de confirmação quando necessário, próximos passos) aplicado às respostas corretas: **M1 = 2.57/5** e **M2 = 5.0/5**. O M2 foi escolhido por ser mais consistente e transparente, ao custo de respostas mais longas (889 contra 355 caracteres em média). Observação: o M2 foi desenhado para cumprir o checklist, então a comparação mostra consistência de formato, não preferência de usuários.

## 5. Testes, indicadores e interpretação
**Plano:** 34 perguntas em `data/testes.json`: diretas, reformulações (inclusive difíceis), fora do tema e situações-limite (entrada vazia, entrada inválida, consulta ambígua e ausência de resposta confiável). Para cada caso registra-se resposta esperada, obtida, acerto/erro e tempo de consulta (média de 200 repetições). Resultados em `docs/resultados_testes.csv` e `docs/indicadores.json`.

| Indicador | Estratégia A | Estratégia B |
|---|---|---|
| Acertos | 30/34 | 28/34 |
| **Taxa de acerto** | **88.2%** | 82.4% |
| Tempo médio por consulta | 0.4161 ms | 0.0247 ms |

Acertos da estratégia A por tipo de pergunta:

| Tipo | Acertos |
|---|---|
| direta | 14/14 |
| reformulação | 8/8 |
| fora do tema | 2/2 |
| limites (vazia, inválida, ambígua, sem resposta) | 5/5 |
| reformulação difícil | 1/5 |

**Facilidade de uso:** roteiro de 5 tarefas executado de forma automatizada (5/5 concluídas; média de 3.0 entradas por tarefa; mensagens de erro compreensíveis verificadas). Um roteiro automático não substitui um usuário real.

**Interpretação:** a estratégia A (estratégia padrão) acertou mais e tolera melhor consultas curtas; B é mais rápida em média, mas tende a diluir a pontuação em perguntas curtas. As falhas se concentram em *reformulações difíceis*: variações de palavra ("nasceu" x "nascimento", "aposentar" x "aposentadoria") que o radical simples não captura. Nesses casos o sistema errou "para o lado seguro" (disse que não tinha resposta ou pediu confirmação), sem inventar orientação.

**Melhorias possíveis:** (1) dicionário de sinônimos e radicalização melhor (stemming em português); (2) mais registros e variações de palavras-chave, validadas com usuários reais.

**Limitações da avaliação:** base e testes foram escritos pela mesma equipe (vocabulário parecido), conjunto pequeno, tempos medidos em uma máquina, sem usuários externos.

### Resultados por pergunta
| Id | Pergunta | Esperado | Obtido (A) | A | Obtido (B) | B |
|---|---|---|---|---|---|---|
| T01 | Como consultar a situação do meu CPF? | D01 | D01 | acerto | D01 | acerto |
| T02 | Como emitir a Carteira de Identidade Nacional? | D02 | D02 | acerto | D02 | acerto |
| T03 | Onde faço a certidão de nascimento do meu filho? | D03 | D03 | acerto | D03 | acerto |
| T04 | Como consultar meu local de votação? | D04 | D04 | acerto | D04 | acerto |
| T05 | Como solicitar o passaporte? | D05 | D05 | acerto | D05 | acerto |
| T06 | Como acessar a Carteira de Trabalho Digital? | D06 | D06 | acerto | D06 | acerto |
| T07 | Como agendar perícia no INSS? | S01 | S01 | acerto | S01 | acerto |
| T08 | Como funciona o atendimento no SUS? | S02 | S02 | acerto | S02 | acerto |
| T09 | Onde tomar vacina de graça? | S03 | S03 | acerto | S03 | acerto |
| T10 | Como pedir o seguro-desemprego? | S04 | S04 | acerto | S04 | acerto |


## 6. Como executar
Requisitos: Python 3.8+ (somente biblioteca padrão, sem instalar nada).

```
python src/sistema.py            # interface interativa
python src/sistema.py --testes   # executa testes e indicadores
```

## 7. Exemplos
```
> Como pedir seguro-desemprego?
ASSUNTO: Como pedir o seguro-desemprego?
ORIENTAÇÃO: ... prazo que em geral vai de 7 a 120 dias ...
FONTE CONSULTADA: https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/seguro-desemprego
ATENÇÃO: confirme requisitos, valores e prazos atualizados na fonte oficial.

> (Enter vazio)     -> "Você não digitou nada. ..."
> 9                 -> "Opção inexistente. Escolha um número de 0 a 5."
> carteira          -> lista de opções (Identidade, Trabalho) para escolher
> Como fazer bolo?  -> "Não encontrei orientação confiável na base ..." + temas alternativos
```

## 8. Cuidados: clareza, acessibilidade, privacidade e informação não oficial
- Linguagem simples, frases curtas, texto puro (sem emojis ou cores), compatível com leitores de tela.
- Nenhum dado pessoal é solicitado, armazenado ou enviado; funciona offline.
- Aviso permanente de que não é canal oficial; toda resposta traz fonte e data de verificação.
- Orientações são resumos: **confirme sempre na fonte oficial** antes de agir.

### Principais fontes da base
- **D01** (documentos): https://www.gov.br/receitafederal/pt-br/assuntos/meu-cpf 
- **D02** (documentos): https://www.gov.br/governodigital/pt-br/identidade/carteira-de-identidade-nacional 
- **D03** (documentos): https://www.planalto.gov.br/ccivil_03/leis/l9534.htm
- **D04** (documentos): https://www.tse.jus.br/eleitor/titulo-e-local-de-votacao
- **D05** (documentos): https://www.gov.br/pf/pt-br/assuntos/passaporte 
- **D06** (documentos): https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/carteira-de-trabalho 


## 9. Conclusões, limitações e melhorias
O protótipo cumpre o fluxo completo: pergunta ou menu, busca, resposta com fonte, aviso de limitação e navegação entre assuntos. Limitações: base pequena (de 19 registros), busca lexical sem entendimento de sentido, informações públicas mudam e exigem revisão periódica. Melhorias: sinônimos, mais temas e fontes locais (município/estado), interface web e testes com usuários reais.

Uso de IA documentado em `docs/uso_ia.md`.

# Plano do estudo exploratório de acompanhamento

Este plano foi fixado antes da execução de acompanhamento. O piloto anterior, sobre o defeito #4417, permanece registrado com sua suíte e sua medição originais.

- Revisões oficiais 2.22.2 e 2.23.0, mesmas do piloto. A seleção intencional inclui os defeitos funcionais #4417 e #4698, ambos documentados pelo projeto e corrigidos em 2.23.0. As revisões também incluem outras mudanças.
- Manter os nove testes originais e acrescentar quatro testes de semana ISO. Os candidatos e sua ordem original são fixados antes da coleta.
- Medir cinco durações em fixed e usar a mediana de cada teste. Capturar LCOV de linha individualmente. Reusar todo o diff do arquivo entre as distribuições.
- Gerar o CARP, cinco controles determinísticos e cinco ordens aleatórias com sementes 17, 23, 47, 83 e 101. Gravar as ordens antes de consultar o oráculo.
- Reexecutar cada ordem completa em buggy em três blocos, com ordem das estratégias embaralhada pelas sementes 137, 271 e 509. Usar o mesmo resultado de uma execução ordenada para avaliar os dois defeitos.
- Reportar posição, APFD, APFDc e tempo acumulado das subprovas. Resumir o tempo por mediana e faixa entre os três blocos. Reportar as cinco ordens aleatórias como variação dentro de cada defeito, sem tratá-las como cinco defeitos.
- Preservar todas as estratégias e blocos no resultado bruto. Se um teste falhar em fixed ou o conjunto de falhas em buggy divergir do esperado, registrar a condição antes de interpretar. A escala e a dependência entre casos impedem inferência populacional.

# Guia

Passo a passo para gerar a primeira leva. Windows.

## 1. Ferramentas

- Rust (`rustc`, `cargo`)
- Python 3.11 ou mais novo
- `pip install httpx pillow`
- [9Router](https://github.com) local autenticado no Grok e/ou no Codex.
  Sem isso a janela sobe, o disparo falha na hora de gerar.

Clona o repo e entra nele. A raiz precisa ter `ALVOS/`, `PROMPTS/` e
`skills/imageproductionfactory/`.

## 2. Sobe o Estúdio

```
cd apps/factory-studio
cargo run
```

A janela "Estúdio — Fábrica de imagem" abre. Não uses o browser
apontando para localhost: isso é o motor por baixo, a cara é a janela.

Para sair, fecha a janela. Isso mata o processo.

## 3. Primeira pessoa

1. Em **Pessoa**, escreve um nome (ex. ANA) e **Criar**.
2. **Adicionar fotos**: uma a três fotos reais do rosto. JPEG ou PNG.
3. Confere as miniaturas. Se não aparecer, o arquivo não é imagem
   (atalho, LFS, arquivo de 130 bytes).

## 4. Escolhe o que gerar

Três modos:

**Biblioteca inteira.** Os 517 casos da fonte, com a pessoa no lugar de
quem a peça pede. Produto, marca, interface e lugar ficam como a fonte
escreveu. Leva horas.

**Casos escolhidos.** Até 20 por disparo. Filtra por propósito ou
categoria, marca no grid, gera. Bom para testar.

**Templates.** Os 47 templates da fila. Mais curto que a biblioteca.

Provedor: Codex é o que tem se saído melhor nas levas longas. Grok
precisa de crédito na conta. **Os dois** faz as duas filas, uma depois
da outra.

Nome desta leva: um apelido (`estudio-v1`, `teste-retrato`). Cada leva
cai em `ALVOS/<NOME>/PRODUCOES/<leva>/`.

A caixa **Só montar os prompts** não chama a API. Serve para ver se
a fila fecha sem erro.

## 5. Durante a geração

O botão vira **Gerando…**. O texto abaixo mostra o tempo e a peça
atual. Cada Codex demora 1 a 2 min. A primeira é a mais lenta.

**Parar** mata a fila inteira. Peças já salvas ficam.

A galeria da direita enche conforme sai. **Abrir galeria** escreve um
HTML lado a lado e abre no navegador.

## 6. Levas velhas

Em **Bibliotecas já geradas** cada pessoa tem as levas com data e
contagem. **Abrir** reconstrói o HTML e abre.

Se a linha diz **não dá para abrir**, os arquivos não estão no disco
(quase sempre Git LFS que nunca baixou). A leva existe no nome, as
imagens não.

## 7. Linha de comando

A janela só dispara o runner Python. O mesmo comando, à mão:

```
python skills/imageproductionfactory/scripts/image_production_factory.py full-library --target ANA --focus estudio-v1 --providers codex
```

Outros: `selected-library --case-ids 8,50,511`, `full-templates`,
`--dry-run`, `--copy-language "English"`.

## Problemas comuns

**Parar não faz nada.** Fecha a janela e mata o Python da fábrica no
gerenciador de tarefas. Na versão atual o Parar corta a árvore de
processo. Se uma janela antiga ainda estiver aberta, usa a nova.

**Grok 400, imagem inválida.** Tinha arquivo morto no alvo. O runner
agora ignora o que não é JPEG/PNG de verdade.

**Grok 403.** Crédito ou limite da conta. Codex segue separado.

**Janela abre e a lista está vazia.** Estás fora da raiz do repo.
Roda o `cargo run` de `apps/factory-studio` com o clone completo.

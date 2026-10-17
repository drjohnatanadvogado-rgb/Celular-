# Cuello – Homenagem pré-final da Sul-Americana 🐓

Editor automático no estilo dos edits do Neymar no YouTube: os cortes caem
**na batida da música** (*Cumbia de los Trapos*), com transições pela torcida
do Galo, flash, tremor, câmera lenta, zoom no rosto e congelamento.

## 1. Instalar

- [ffmpeg](https://ffmpeg.org/download.html) (no Windows: `winget install ffmpeg`;
  no Mac: `brew install ffmpeg`)
- Python 3 + numpy: `pip install numpy`

Teste sem nenhum material (gera clipes e batida falsos em `demo/saida/demo.mp4`):

```bash
python3 editar.py --demo
```

## 2. Juntar o material

Coloque a música em `musica/cumbia_de_los_trapos.mp3` e os clipes em `clipes/`
com estes nomes (ou troque os nomes no `roteiro.json`):

| Arquivo              | O que é                                                  |
|----------------------|----------------------------------------------------------|
| `torcida_1.mp4`      | Torcida cantando na Arena MRV / Mineirão (com som)        |
| `torcida_2.mp4`      | Torcida pulando, bandeirão, sinalizadores                 |
| `aquecimento.mp4`    | Cuello aquecendo, entrando em campo, concentração         |
| `skills.mp4`         | Dribles, canetas, chapéus (um clipe com vários lances)    |
| `gol_1.mp4`, `gol_2.mp4` | Gols e comemorações                                  |
| `rosto_rindo.mp4`    | Close do Cuello rindo/sorrindo                            |

Dicas:
- Use vídeos de **alta qualidade** (1080p+). Gravações próprias da arquibancada
  funcionam muito bem nas transições de torcida.
- Um clipe pode conter vários lances: no roteiro você escolhe de que segundo
  cada corte começa (`"inicio"`).

## 3. Ajustar o roteiro

`roteiro.json` já vem montado com a estrutura clássica desses edits (~50 s):

1. **Intro** – 4 s só com o canto da torcida em preto e branco + “FINAL DA SUL-AMERICANA 2026”
2. **A música entra** – Cuello aquecendo, intercalado com a torcida a cada 2 batidas
3. **Drop** – skills com um corte por batida, glitch, tremor e câmera lenta
4. **Gols** – câmera lenta + explosão da torcida (som original misturado)
5. **Rosto rindo** – zoom lento no rosto, congela, flash
6. **Final** – torcida + “RUMO AO TÍTULO” → “VAMOS, GALO!”

Antes de editar, veja as batidas que o programa detectou na música:

```bash
python3 editar.py roteiro.json --batidas
```

Depois de colocar seus clipes, assista cada trecho e ajuste o `"inicio"`
(segundo do clipe onde o lance começa). Para gerar o vídeo:

```bash
python3 editar.py roteiro.json
```

O resultado sai em `saida/cuello_homenagem.mp4`.

### Opções de cada trecho

| Campo        | Exemplo | Efeito |
|--------------|---------|--------|
| `arquivo`    | `"skills.mp4"` | clipe dentro de `clipes/` |
| `inicio`     | `12.5` | segundo do clipe onde o corte começa |
| `batidas`    | `2` | duração em batidas (o corte sempre cai na batida) |
| `segundos`   | `4.0` | duração em segundos (útil na intro antes da música) |
| `velocidade` | `0.5` | câmera lenta (`0.5` = metade) ou acelerado (`1.5`) |
| `suave`      | `true` | câmera lenta com interpolação de quadros (mais lento de renderizar) |
| `congelar`   | `1.2` | congela o último quadro por N segundos |
| `som`        | `0.6` | volume do som original do clipe (torcida); `0` = mudo |
| `pb`         | `true` | preto e branco (as cores do Galo) |
| `zoom`       | `{"de":1,"ate":1.9,"x":0.5,"y":0.3}` | aproxima até o ponto x/y (0–1) – use no rosto |
| `efeitos`    | `["flash","tremor"]` | `flash`, `flash_fim`, `pulso`, `tremor`, `glitch`, `fade_entrada`, `fade_saida` |
| `textos`     | `[{"texto":"VAMOS, GALO!","posicao":"meio","tamanho":0.12,"inicio":0.5}]` | posição `cima`/`meio`/`baixo` |

### Opções gerais

- `formato`: `"16:9"` (YouTube), `"9:16"` (Reels/TikTok/Status) ou `"1:1"`
- `atraso_musica`: segundos de intro antes da música começar
- `musica_inicio`: pular o começo da música (ex.: começar direto no refrão)
- `bpm` + `primeira_batida`: forçar a grade manualmente se a detecção errar
- `cor`: `{"contraste":1.12,"saturacao":1.15}` · `vinheta`: `true/false`

> ⚠️ Direitos autorais: a música e as imagens de transmissão pertencem aos
> seus donos. Para postar sem dor de cabeça, use em perfil pessoal sem
> monetização — o YouTube pode aplicar Content ID na música.

#!/usr/bin/env python3
"""Editor automático de "edit" de futebol sincronizado com a batida da música.

Uso:
    python3 editar.py roteiro.json            # gera o vídeo
    python3 editar.py roteiro.json --batidas  # só mostra BPM e batidas detectadas
    python3 editar.py --demo                  # gera clipes/música de teste e renderiza

Requisitos: ffmpeg/ffprobe no PATH, Python 3.8+ e numpy.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FORMATOS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


def rodar(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode(errors="replace")[-3000:])
        raise SystemExit("Erro ao rodar: " + " ".join(cmd[:6]) + " ...")
    return r.stdout


def tem_audio(caminho):
    out = rodar(["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", caminho])
    return bool(out.strip())


# ---------------------------------------------------------------- batidas

def detectar_batidas(musica, inicio=0.0, sr=22050):
    """Retorna (bpm, lista de tempos das batidas em segundos, relativos a `inicio`)."""
    pcm = rodar(["ffmpeg", "-v", "error", "-ss", str(inicio), "-i", musica,
                 "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"])
    y = np.frombuffer(pcm, dtype=np.float32)
    if len(y) < sr * 4:
        raise SystemExit("Música muito curta para detectar batidas.")
    n_fft, hop = 2048, 512
    janela = np.hanning(n_fft).astype(np.float32)
    n = 1 + (len(y) - n_fft) // hop
    quadros = np.lib.stride_tricks.as_strided(
        y, shape=(n, n_fft), strides=(y.strides[0] * hop, y.strides[0]))
    espec = np.log1p(100 * np.abs(np.fft.rfft(quadros * janela, axis=1)))
    fluxo = np.maximum(0, np.diff(espec, axis=0)).sum(axis=1)
    fluxo = np.concatenate([[0], fluxo])
    # remove tendência lenta e normaliza
    suave = np.convolve(fluxo, np.ones(16) / 16, mode="same")
    env = np.maximum(0, fluxo - suave)
    env /= env.max() + 1e-9
    fps = sr / hop

    # tempo por autocorrelação, com preferência em torno de 110 BPM
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    melhor, bpm = -1, 100.0
    for b in np.arange(70, 180, 0.25):
        lag = 60 * fps / b
        lo = int(lag)
        v = ac[lo] * (1 - (lag - lo)) + ac[lo + 1] * (lag - lo)
        v *= math.exp(-0.5 * (math.log2(b / 110) / 0.9) ** 2)
        if v > melhor:
            melhor, bpm = v, b
    # refina BPM e fase juntos (um BPM levemente errado acumula deriva)
    pos = np.arange(len(env))
    melhor = -1
    for b in np.arange(bpm - 1.5, bpm + 1.5, 0.02):
        per = 60 * fps / b
        k = np.arange(int((len(env) - 1) / per))
        for off in np.arange(0, per, 0.5):
            v = np.interp(off + k * per, pos, env).sum() / len(k)
            if v > melhor:
                melhor, bpm_f, fase = v, b, off
    bpm = float(bpm_f)
    periodo = 60 * fps / bpm
    k = np.arange(int((len(env) - 1 - fase) / periodo) + 1)
    # ajuste fino de cada batida no pico mais próximo
    raio = max(1, int(periodo * 0.08))
    batidas = []
    for i in k:
        c = int(fase + i * periodo)
        a, b = max(0, c - raio), min(len(env), c + raio + 1)
        if a >= b:
            continue
        p = a + int(np.argmax(env[a:b]))
        batidas.append(((p if env[p] > 0.05 else c) * hop + n_fft / 2) / sr)
    # recupera batidas no comecinho que a análise não enxerga
    while batidas and batidas[0] - 60 / bpm > -0.05:
        batidas.insert(0, max(0.0, batidas[0] - 60 / bpm))
    return bpm, batidas


def grade_manual(bpm, primeira, duracao):
    p = 60.0 / bpm
    return [primeira + i * p for i in range(int((duracao - primeira) / p) + 1)]


def duracao_midia(caminho):
    out = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", caminho])
    return float(out.strip())


# ---------------------------------------------------------------- filtros

def esc(v):
    return str(v).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def filtros_video(seg, W, H, fps, dur, global_cfg, fonte, tmpdir, idx):
    """Monta a cadeia de filtros de vídeo de um trecho."""
    vel = float(seg.get("velocidade", 1.0))
    f = [f"setpts=(PTS-STARTPTS)/{vel}"]
    if seg.get("suave") and vel < 1:
        f.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1")
    f += [f"fps={fps}",
          f"scale={W}:{H}:force_original_aspect_ratio=increase",
          f"crop={W}:{H}", "setsar=1",
          # garante a duração exata (congela o último quadro se faltar vídeo)
          f"tpad=stop_mode=clone:stop_duration={dur + 1}",
          f"trim=duration={dur}", "setpts=PTS-STARTPTS"]
    efeitos = seg.get("efeitos", [])
    if isinstance(efeitos, str):
        efeitos = [efeitos]

    zoom = seg.get("zoom")
    if "pulso" in efeitos and not zoom:
        zoom = {"de": 1.18, "ate": 1.0, "duracao": 0.25}
    if zoom:
        z0, z1 = float(zoom.get("de", 1.0)), float(zoom.get("ate", 1.5))
        zd = float(zoom.get("duracao", dur))
        zx, zy = float(zoom.get("x", 0.5)), float(zoom.get("y", 0.4))
        p = f"min(it/{zd},1)"
        e = f"({p}*{p}*(3-2*{p}))"  # smoothstep
        # sobe a resolução antes do zoompan para evitar tremido de arredondamento
        f.append(f"scale={W * 2}:{H * 2}")
        f.append(
            f"zoompan=z='{z0}+({z1}-{z0})*{e}'"
            f":x='(iw-iw/zoom)*{zx}':y='(ih-ih/zoom)*{zy}'"
            f":d=1:s={W}x{H}:fps={fps}")
    if "tremor" in efeitos:
        f.append(f"scale={int(W * 1.08) // 2 * 2}:{int(H * 1.08) // 2 * 2}")
        f.append(f"crop={W}:{H}:x='(iw-ow)/2+(iw-ow)/2*sin(t*53)*exp(-t*4)'"
                 f":y='(ih-oh)/2+(ih-oh)/2*cos(t*41)*exp(-t*4)'")
    if seg.get("pb") or global_cfg.get("pb"):
        f.append("hue=s=0")
    if "glitch" in efeitos:
        f.append("rgbashift=rh=-14:bh=14:enable='lt(t,0.18)'")
    if "flash" in efeitos:
        f.append("eq=eval=frame:brightness='0.85*max(0,1-t/0.14)'")
    cor = global_cfg.get("cor", {"contraste": 1.1, "saturacao": 1.2})
    if cor:
        f.append(f"eq=contrast={cor.get('contraste', 1)}"
                 f":saturation={cor.get('saturacao', 1)}"
                 f":brightness={cor.get('brilho', 0)}")
    if global_cfg.get("vinheta", True):
        f.append("vignette=PI/5")
    if "flash_fim" in efeitos:
        f.append(f"eq=eval=frame:brightness='0.85*max(0,1-({dur}-t)/0.14)'")
    if "fade_entrada" in efeitos:
        f.append("fade=t=in:st=0:d=0.5")
    if "fade_saida" in efeitos:
        f.append(f"fade=t=out:st={max(0, dur - 0.8)}:d=0.8")

    textos = seg.get("textos") or ([{"texto": seg["texto"]}] if seg.get("texto") else [])
    for j, t in enumerate(textos):
        if not fonte:
            print("  aviso: nenhuma fonte encontrada, texto ignorado")
            break
        arq = os.path.join(tmpdir, f"txt_{idx}_{j}.txt")
        with open(arq, "w", encoding="utf-8") as fh:
            fh.write(t["texto"])
        ini = float(t.get("inicio", 0))
        fim = float(t.get("fim", dur))
        tam = int(t.get("tamanho", 0.09) * H) if float(t.get("tamanho", 0.09)) < 1 else int(t["tamanho"])
        pos_y = {"cima": "h*0.12", "meio": "(h-text_h)/2", "baixo": "h*0.80-text_h"}
        y = pos_y.get(t.get("posicao", "baixo"), "h*0.80-text_h")
        alfa = f"min(1,(t-{ini})/0.2)"
        f.append(
            f"drawtext=fontfile='{esc(fonte)}':textfile='{esc(arq)}':expansion=none"
            f":fontsize={tam}:fontcolor={t.get('cor', 'white')}"
            f":borderw={max(2, tam // 18)}:bordercolor=black"
            f":x=(w-text_w)/2:y={y}:alpha='{alfa}'"
            f":enable='between(t,{ini},{fim})'")
    f.append("format=yuv420p")
    return ",".join(f)


def filtros_audio(seg, dur):
    vel = float(seg.get("velocidade", 1.0))
    f = []
    v = vel
    while v > 2.0:
        f.append("atempo=2.0")
        v /= 2.0
    while v < 0.5:
        f.append("atempo=0.5")
        v /= 0.5
    if abs(v - 1) > 1e-6:
        f.append(f"atempo={v}")
    f += ["aresample=48000", "aformat=channel_layouts=stereo",
          f"apad=whole_dur={dur}", f"atrim=duration={dur}",
          f"volume={float(seg.get('som', 0))}"]
    return ",".join(f)


# ---------------------------------------------------------------- render

def renderizar(cfg, base, saida_override=None, so_batidas=False):
    W, H = FORMATOS.get(cfg.get("formato", "16:9"), FORMATOS["16:9"])
    fps = int(cfg.get("fps", 30))
    musica = os.path.join(base, cfg["musica"])
    m_ini = float(cfg.get("musica_inicio", 0))
    atraso = float(cfg.get("atraso_musica", 0))
    pasta = os.path.join(base, cfg.get("pasta_clipes", "clipes"))
    saida = saida_override or os.path.join(base, cfg.get("saida", "saida/edit.mp4"))

    if cfg.get("bpm"):
        bpm = float(cfg["bpm"])
        batidas = grade_manual(bpm, float(cfg.get("primeira_batida", 0)),
                               duracao_midia(musica) - m_ini)
    else:
        bpm, batidas = detectar_batidas(musica, m_ini)
    batidas = [atraso + b for b in batidas]
    print(f"BPM: {bpm:.1f}  |  {len(batidas)} batidas  |  primeiras: "
          + ", ".join(f"{b:.2f}s" for b in batidas[:8]))
    if so_batidas:
        return

    # define onde cada corte cai na linha do tempo (sempre numa batida)
    cortes, t, b_idx = [0.0], 0.0, 0
    for seg in cfg["trechos"]:
        if "segundos" in seg:
            t += float(seg["segundos"])
            # alinha o próximo índice de batida ao tempo atual
            while b_idx < len(batidas) and batidas[b_idx] < t - 1e-3:
                b_idx += 1
            if seg.get("cortar_na_batida", True) and b_idx < len(batidas) and t > atraso:
                t = batidas[b_idx]
        else:
            while b_idx < len(batidas) and batidas[b_idx] < t - 1e-3:
                b_idx += 1
            b_idx += int(seg.get("batidas", 2))
            if b_idx < len(batidas):
                t = batidas[b_idx]
            else:
                t += int(seg.get("batidas", 2)) * 60.0 / bpm
        cortes.append(t)

    fonte = next((p for p in [cfg.get("fonte")] + FONTES if p and os.path.exists(p)), None)
    tmpdir = tempfile.mkdtemp(prefix="edit_")
    partes = []
    try:
        for i, seg in enumerate(cfg["trechos"]):
            dur = round(cortes[i + 1] - cortes[i], 4)
            if dur <= 0.05:
                print(f"  trecho {i + 1} ignorado (duração {dur:.3f}s)")
                continue
            arq = os.path.join(pasta, seg["arquivo"])
            if not os.path.exists(arq):
                raise SystemExit(f"Clipe não encontrado: {arq}")
            vel = float(seg.get("velocidade", 1.0))
            congela = float(seg.get("congelar", 0))
            dur_fonte = max(0.05, (dur - congela) * vel)
            print(f"[{i + 1:02d}/{len(cfg['trechos'])}] {cortes[i]:6.2f}s +{dur:.2f}s  "
                  f"{seg['arquivo']}  {seg.get('efeitos', '')}")
            vf = filtros_video(seg, W, H, fps, dur, cfg, fonte, tmpdir, i)
            af = filtros_audio(seg, dur)
            out = os.path.join(tmpdir, f"p{i:03d}.mp4")
            cmd = ["ffmpeg", "-v", "error", "-y",
                   "-ss", str(seg.get("inicio", 0)), "-t", f"{dur_fonte:.4f}", "-i", arq]
            if tem_audio(arq):
                amap = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                amap = "1:a:0"
            cmd += ["-filter_complex", f"[0:v:0]{vf}[v];[{amap}]{af}[a]",
                    "-map", "[v]", "-map", "[a]", "-t", str(dur),
                    "-c:v", "libx264", "-preset", cfg.get("preset", "medium"), "-crf", "18",
                    "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out]
            rodar(cmd)
            partes.append(out)

        lista = os.path.join(tmpdir, "lista.txt")
        with open(lista, "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in partes)
        junto = os.path.join(tmpdir, "junto.mp4")
        rodar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", lista, "-c", "copy", junto])

        total = duracao_midia(junto)
        vol_m = float(cfg.get("volume_musica", 1.0))
        fade = float(cfg.get("fade_final", 2.0))
        atraso_ms = int(atraso * 1000)
        af = (f"[1:a]atrim=duration={max(0.1, total - atraso)},aresample=48000,"
              f"aformat=channel_layouts=stereo,volume={vol_m},"
              f"afade=t=out:st={max(0, total - atraso - fade)}:d={fade},"
              f"adelay={atraso_ms}|{atraso_ms}[m];"
              f"[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
        rodar(["ffmpeg", "-v", "error", "-y", "-i", junto,
               "-ss", str(m_ini), "-i", musica,
               "-filter_complex", af, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
               "-movflags", "+faststart", "-t", str(total), saida])
        print(f"\nPronto! {saida}  ({total:.1f}s, {W}x{H} @ {fps}fps)")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- demo

def gerar_demo(pasta_demo):
    """Cria clipes falsos e uma batida de cumbia sintética para testar o editor."""
    os.makedirs(os.path.join(pasta_demo, "clipes"), exist_ok=True)
    os.makedirs(os.path.join(pasta_demo, "musica"), exist_ok=True)
    fonte = next((p for p in FONTES if os.path.exists(p)), None)
    clipes = {
        "torcida_1.mp4": ("0x202020", "TORCIDA CANTANDO"),
        "torcida_2.mp4": ("0x303030", "TORCIDA PULANDO"),
        "aquecimento.mp4": ("0x1a3d1a", "CUELLO AQUECENDO"),
        "skills.mp4": ("0x14324a", "CUELLO SKILL"),
        "gol_1.mp4": ("0x4a1414", "CUELLO GOL 1"),
        "gol_2.mp4": ("0x4a3014", "CUELLO GOL 2"),
        "rosto_rindo.mp4": ("0x3a144a", "CUELLO RINDO"),
    }
    for nome, (cor, txt) in clipes.items():
        dt = (f",drawtext=fontfile='{esc(fonte)}':text='{txt}':fontsize=90:fontcolor=white"
              f":x=(w-text_w)/2+sin(t*2)*200:y=(h-text_h)/2" if fonte else "")
        rodar(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
               "-i", f"color=c={cor}:s=1280x720:d=12:r=30",
               "-f", "lavfi", "-i", "anoisesrc=d=12:c=pink:a=0.2",
               "-vf", f"drawgrid=w=80:h=80:t=2:c=white@0.25{dt}",
               "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
               "-c:a", "aac", os.path.join(pasta_demo, "clipes", nome)])
    # cumbia sintética a 96 BPM: bumbo nos tempos, guacharaca nas semicolcheias
    bpm = 96
    b = 60 / bpm
    expr = (f"0.9*sin(2*PI*55*t)*exp(-30*mod(t,{b}))"
            f"+0.25*(random(0)-0.5)*exp(-60*mod(t,{b / 4}))"
            f"+0.35*sin(2*PI*220*t)*exp(-12*mod(t+{b / 2},{b}))")
    rodar(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"aevalsrc='{expr}':s=44100:d=60",
           "-c:a", "libmp3lame", "-q:a", "4",
           os.path.join(pasta_demo, "musica", "musica.mp3")])
    with open(os.path.join(AQUI, "roteiro.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["musica"] = "musica/musica.mp3"
    cfg["saida"] = "saida/demo.mp4"
    cfg["preset"] = "veryfast"
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roteiro", nargs="?", default=os.path.join(AQUI, "roteiro.json"))
    ap.add_argument("--batidas", action="store_true", help="só detectar e mostrar as batidas")
    ap.add_argument("--saida", help="caminho do vídeo final")
    ap.add_argument("--demo", action="store_true", help="testar com clipes e música sintéticos")
    a = ap.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("Instale o ffmpeg primeiro (https://ffmpeg.org/download.html).")
    if a.demo:
        base = os.path.join(AQUI, "demo")
        cfg = gerar_demo(base)
    else:
        with open(a.roteiro, encoding="utf-8") as fh:
            cfg = json.load(fh)
        base = os.path.dirname(os.path.abspath(a.roteiro))
    renderizar(cfg, base, a.saida, a.batidas)


if __name__ == "__main__":
    main()

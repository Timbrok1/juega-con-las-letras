#!/usr/bin/env python3
"""Prueba de punta a punta en Chromium sin interfaz (Playwright).

Sirve la web en una subcarpeta (como GitHub Pages), espera a que el service
worker guarde todos los audios, pasa por los juegos comprobando que suenan los
MP3, prueba las peticiones Range (iOS) y repite todo SIN CONEXIÓN.

Instalación (una vez):
    ~/.venvs/juego-lectura/bin/pip install -r tools/requirements-test.txt
    ~/.venvs/juego-lectura/bin/python -m playwright install --only-shell chromium
Uso:
    ~/.venvs/juego-lectura/bin/python tools/test_e2e.py [carpeta_capturas]
"""
import subprocess,sys,time,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
OUT=sys.argv[1] if len(sys.argv)>1 else tempfile.mkdtemp();PORT=8765
srv=subprocess.Popen([sys.executable,'-m','http.server',str(PORT),'--bind','127.0.0.1','--directory',str(ROOT.parent)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(1.5);URL=f'http://localhost:{PORT}/{ROOT.name}/'
res=[]
def ok(c,m):res.append(bool(c));print(('OK   ' if c else 'FALLO ')+m)
try:
 with sync_playwright() as p:
  b=p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
  ctx=b.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
  # registra qué MP3 se reproducen (solo para la prueba)
  ctx.add_init_script("window.__played=[];const _p=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){if(!this.src.startsWith('data:'))window.__played.push(decodeURIComponent(this.src.split('/audio/')[1]||this.src));return _p.call(this)};")
  pg=ctx.new_page();errs=[]
  pg.on('pageerror',lambda e:errs.append(str(e)));pg.on('console',lambda m:m.type=='error' and errs.append(m.text))
  pg.goto(URL);pg.evaluate('navigator.serviceWorker.ready.then(()=>1)');pg.reload()
  pg.wait_for_function('!!navigator.serviceWorker.controller',timeout=15000);ok(True,'service worker activo')
  pg.evaluate("navigator.serviceWorker.controller.postMessage('sync')");t0=time.time()
  NA=pg.evaluate("fetch('audio/manifest.json').then(r=>r.json()).then(m=>m.files.length)")
  pg.wait_for_function(f"caches.open('media').then(c=>c.keys()).then(k=>window.__n=k.length)&&window.__n>={NA}",timeout=60000,polling=500)
  ok(True,f'{NA} audios en caché ({time.time()-t0:.1f}s)')
  ok(pg.evaluate("Promise.all([document.fonts.load('700 40px Andika'),document.fonts.load('800 20px Nunito')]).then(r=>r[0].length>0&&r[1].length>0)"),'fuentes locales cargadas')
  r=pg.evaluate("""async()=>{const h=(await (await fetch('audio/manifest.json')).json()).huellas.pa;const u='audio/pa.mp3?v='+h;
     const full=new Uint8Array(await (await fetch(u)).arrayBuffer());const rr=await fetch(u,{headers:{Range:'bytes=10-109'}});
     const part=new Uint8Array(await rr.arrayBuffer());return {st:rr.status,len:part.length,cr:rr.headers.get('content-range'),same:part.every((x,i)=>x===full[10+i]),size:full.length}}""")
  ok(r['st']==206 and r['len']==100 and r['same'] and r['cr']==f"bytes 10-109/{r['size']}",f'Range -> {r}')
  def juegos(tag):
    pg.evaluate('window.__played=[]')
    pg.click('[data-go=tren]');pg.click('#consRow .chip[data-c=M]');pg.wait_for_timeout(300);pg.click('#vowRow .chip[data-v=A]');pg.click('#join');pg.wait_for_timeout(3500);pg.click('#tren [data-back]')
    pg.click('[data-go=caza]');pg.wait_for_timeout(700)
    for bb in pg.query_selector_all('#bubbles .bubble'):
      bb.click();pg.wait_for_timeout(300)
      if 'ok' in (bb.get_attribute('class') or ''):break
    pg.wait_for_timeout(600);pg.click('#caza [data-back]')
    pg.click('[data-go=palabra]');pg.wait_for_timeout(600);pg.click('#pic');pg.wait_for_timeout(600);pg.click('#palabra [data-back]')
    pg.click('[data-go=lee]');pg.wait_for_timeout(300);w=pg.inner_text('#leeWord');pg.click('#lee [data-back]')
    pl=pg.evaluate('window.__played')
    ok(any(x.startswith('eme.mp3') for x in pl) and any(x.startswith('la-eme-con-la-a.mp3') for x in pl) and any(x.startswith('ma.mp3') for x in pl) and any(x.startswith('muy-bien') for x in pl),f'[{tag}] suenan MP3: {pl[:9]}')
    ok(len(w)>1,f'[{tag}] Lee y elige: {w}')
  juegos('con red');pg.screenshot(path=f'{OUT}/home.png')
  # Encuentra la letra: suena el nombre, se acierta, la estrella sube
  pg.evaluate('window.__played=[]');s0=pg.evaluate("JSON.parse(localStorage.getItem('lecturaCasa')).stars")
  pg.click('[data-go=letra]');pg.wait_for_timeout(2600)
  pl=pg.evaluate('window.__played');ok(any(x.startswith('escucha-y-toca-la-letra') for x in pl),f'letra: instrucción y nombre {pl[:3]}')
  hecho=False
  for i in range(4):
    for bb in pg.query_selector_all('#letraOpts .bubble'):
      bb.click();pg.wait_for_timeout(250)
      if 'ok' in (bb.get_attribute('class') or ''):hecho=True;break
    if hecho:break
  ok(hecho and len(pg.query_selector_all('#letraOpts .bubble'))>=2,'letra: se puede acertar')
  pg.screenshot(path=f'{OUT}/letra.png');pg.click('#letra [data-back]')
  # Lee la frase: con las letras por defecto hay frases; 3 dibujos distintos
  pg.click('[data-go=frase]');pg.wait_for_timeout(400)
  fr=pg.inner_text('#fraseText');ops=[b.inner_text() for b in pg.query_selector_all('#fraseOpts .bubble')]
  ok(len(fr.split())>=4 and len(ops)==3 and len(set(ops))==3,f'frase: «{fr}» opciones {ops}')
  pg.evaluate('window.__played=[]')
  for bb in pg.query_selector_all('#fraseOpts .bubble'):
    bb.click();pg.wait_for_timeout(300)
    if 'ok' in (bb.get_attribute('class') or ''):break
  pg.wait_for_timeout(2500);pl=pg.evaluate('window.__played')
  ok(any(x.startswith('toma') for x in pl),f'frase: al acertar se lee la frase {pl[-6:]}')
  pg.screenshot(path=f'{OUT}/frase.png');pg.click('#frase [data-back]')
  # fase 3: instrucciones con ❓ e historial de aciertos/fallos
  pg.evaluate('window.__played=[]');pg.click('[data-go=caza]');pg.wait_for_timeout(500);pg.click('#caza [data-help]');pg.wait_for_timeout(300)
  ok(any(x.startswith('escucha-y-toca') for x in pg.evaluate('window.__played')),'botón ❓ repite la instrucción');pg.click('#caza [data-back]')
  st=pg.evaluate("JSON.parse(localStorage.getItem('lecturaCasa')).stats")
  ok(any(k.startswith('s:') for k in st) and any(k.startswith('l:') or k.startswith('w:') for k in st) or any(k.startswith('s:') for k in st),f'historial guardado: {list(st)[:4]}')
  g=pg.query_selector('#gear').bounding_box();pg.mouse.move(g['x']+20,g['y']+20);pg.mouse.down();pg.wait_for_timeout(1700);pg.mouse.up();pg.wait_for_timeout(800)
  ok(pg.is_visible('#padres'),'panel de padres (pulsación larga)')
  print('   offline:',pg.inner_text('#offlineInfo'));print('   voz    :',pg.inner_text('#voiceInfo')[:120])
  ok('Lista para usar sin conexión' in pg.inner_text('#offlineInfo'),'panel: lista sin conexión')
  pg.click('#setCons button[data-c=S]');n0=pg.inner_text('#typesInfo')
  S=pg.evaluate("JSON.parse(localStorage.getItem('lecturaCasa'))")
  nueva=pg.inner_text('#setCons button[data-c=S]')
  ok(S['cons']==['M','P','L','S','T'] and S['newest']=='S' and 'NUEVA' in nueva.upper(),f"activar S -> {S['cons']} (nueva: {S['newest']}, botón: {nueva!r})")
  pg.click('#setTypes button[data-t=cerrada]');n1=pg.inner_text('#typesInfo')
  num=lambda x:int(x.rstrip('.').split()[-1])
  ok(num(n1)>num(n0) and 'cerrada' in pg.evaluate("JSON.parse(localStorage.getItem('lecturaCasa')).sylTypes"),f'tipos de sílaba: «{n0[-30:]}» -> «{n1[-30:]}»')
  print('   cuesta:',pg.inner_text('#hardInfo'))
  pg.locator('#installInfo').scroll_into_view_if_needed();pg.screenshot(path=f'{OUT}/padres.png')
  pg.click('#padres [data-back]')
  srv.terminate();srv.wait();ctx.set_offline(True)
  pg.goto(URL);pg.wait_for_selector('#home.on',timeout=10000);ok(True,'SIN CONEXIÓN: carga')
  ok(pg.evaluate("document.fonts.load('700 40px Andika').then(r=>r.length>0)"),'sin conexión: fuentes')
  juegos('sin red')
  errs=[e for e in errs if 'ERR_INTERNET_DISCONNECTED' not in e]
  ok(not errs,f'sin errores en consola {errs[:5]}')
  b.close()
finally:
  if srv.poll() is None: srv.terminate()
print('RESUMEN:',sum(res),'/',len(res),'· capturas en',OUT)
sys.exit(0 if all(res) else 1)

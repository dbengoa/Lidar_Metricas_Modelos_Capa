"""Human-authorized CNIG baskets and reception of up to twenty separate LAZ files."""
from pathlib import Path
import html
import re
import time

from .core import AuthorizationRequired, atomic_json, las_header

MAX_BATCH_SIZE = 20


def batch_size(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BATCH_SIZE:
        raise ValueError('El tamaño de lote CNIG debe ser un entero entre 1 y 20')
    return value


def prepare(browser, items, number):
    from .browser import BASE, canonical_name
    if not items or len(items) > MAX_BATCH_SIZE:
        raise ValueError('Un lote CNIG debe contener entre 1 y 20 hojas')
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError('Número de lote inválido')
    names = set()
    identifiers = set()
    records = []
    rows = []
    for record, destination in items:
        sec, name = str(record['sec']), str(record['name'])
        key = canonical_name(name)
        if not re.fullmatch(r'\d+', sec) or sec in identifiers:
            raise ValueError('Identificador CNIG inválido o duplicado en el lote')
        if not re.fullmatch(r'[A-Za-z0-9_.+()-]+\.(?:laz|las)', name, re.I) or key in names:
            raise ValueError('Nombre CNIG inválido o ambiguo en el lote')
        names.add(key)
        identifiers.add(sec)
        url = BASE+'detalleArchivo?sec='+sec
        records.append({'sec': sec, 'name': name, 'destination': str(destination), 'detail_url': url})
        rows.append('<tr><td>'+html.escape(name)+'</td><td><a target="_blank" rel="noopener" href="'+url+'">Abrir ficha y añadir a la cesta</a></td></tr>')
    browser.work.mkdir(parents=True, exist_ok=True)
    manifest = browser.work/('lote_cnig_'+str(number)+'.html')
    document = '''<!doctype html><html lang="es"><meta charset="utf-8"><title>Lote CNIG</title>
<body><h1>Lote CNIG '''+str(number)+''' · '''+str(len(items))+''' hojas</h1>
<p>Selección asistida: esta página no añade archivos automáticamente a la cesta.</p>
<ol><li>En las fichas oficiales de la tabla, añada las hojas a la cesta de CNIG.
Revise que la cesta contenga sólo las hojas de este lote: máximo 20 en total.</li>
<li>Abra la <a target="_blank" rel="noopener" href="'''+BASE+'''listaFicheros">cesta oficial</a>,
pulse «Iniciar descarga» y complete los trámites que solicite CNIG en Chrome habitual.</li>
<li>Guarde los LAZ individuales, sin renombrarlos, en <b>'''+html.escape(str(browser.download_directory))+'''</b>.
El complemento reconoce cualquier orden y conserva los originales. No extrae paquetes ZIP.</li>
<li>Cuando termine el lote, revise o retire de la cesta los archivos anteriores antes del siguiente.
Si supera 20 archivos, el portal puede pedir iniciar sesión.</li></ol>
<p>Chrome puede solicitar permiso para descargar varios archivos. La pausa del complemento no pausa Chrome.
No se garantizan una única autorización ni una transferencia conjunta: las decide CNIG.</p>
<table border="1" cellpadding="6"><tr><th>Archivo esperado</th><th>Selección oficial</th></tr>'''+''.join(rows)+'''</table></body></html>'''
    manifest.write_text(document, encoding='utf-8')
    atomic_json(manifest.with_suffix('.json'), {'batch': number, 'maximum': MAX_BATCH_SIZE, 'files': records})
    return manifest


def receive(browser, items, number=1, received=lambda record, path: None):
    from .browser import canonical_name
    manifest = prepare(browser, items, number)
    pending = {canonical_name(record['name']): (record, Path(destination)) for record, destination in items}
    directories = {browser.download_directory}
    for record, destination in pending.values():
        destination.parent.mkdir(parents=True, exist_ok=True)
        directories.update((destination.parent, destination.parent.parent))
    browser.check()
    browser.retry.clear()
    url = manifest.resolve().as_uri()
    browser.navigate(url)
    browser.progress('CNIG autorización: lote '+str(number)+'; añada las '+str(len(items))+
                     ' hojas de la guía a la cesta oficial e inicie la descarga. Máximo 20 en la cesta.')
    browser.progress('CNIG vigilando: lote '+str(number)+'; '+str(len(pending))+' archivos pendientes')
    started = last_report = time.monotonic()
    seen, reported, completed = {}, set(), []
    def checkpoint():
        nonlocal started
        before = time.monotonic()
        browser.check()
        started += time.monotonic()-before

    while pending:
        checkpoint()
        if browser.retry.is_set():
            browser.retry.clear()
            browser.navigate(url)
        candidates = set()
        for directory in directories:
            try:
                candidates.update(directory.iterdir())
            except FileNotFoundError:
                continue
        for candidate in sorted(candidates, key=str):
            checkpoint()
            key = canonical_name(candidate.name)
            if key not in pending or candidate.is_symlink() or not candidate.is_file():
                continue
            record, destination = pending[key]
            if any(candidate.with_name(candidate.name+suffix).exists() for suffix in ('.crdownload', '.part', '.tmp')):
                seen.pop(candidate, None)
                continue
            try:
                stat = candidate.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                previous = seen.get(candidate)
                if previous is None or previous[0] != signature:
                    seen[candidate] = (signature, time.monotonic())
                    continue
                if time.monotonic()-previous[1] < browser.stable_seconds:
                    continue
                result = browser.adopt(candidate, destination, signature, checkpoint)
                las_header(result, True)
            except (OSError, ValueError) as error:
                if candidate not in reported:
                    browser.progress('CNIG esperando archivo completo '+candidate.name+': '+str(error))
                    reported.add(candidate)
                continue
            # Persist each receipt immediately, including when a later file times out.
            received(record, result)
            completed.append(result)
            del pending[key]
            started = time.monotonic()
            browser.progress('CNIG archivo completo incorporado: '+record['name']+
                             '; lote '+str(number)+': '+str(len(completed))+'/'+str(len(items)))
        if not pending:
            break
        if time.monotonic()-started >= browser.timeout:
            raise AuthorizationRequired('Lote '+str(number)+': agotado el tiempo de espera sin incorporar otra hoja. Pendientes: '+
                                        ', '.join(record['name'] for record, dest in pending.values())+
                                        '. Se conservan las hojas completas; reanude con la misma carpeta.')
        if time.monotonic()-last_report >= 10:
            browser.progress('CNIG vigilando: lote '+str(number)+'; pendientes '+str(len(pending)))
            last_report = time.monotonic()
        time.sleep(browser.poll)
    return completed

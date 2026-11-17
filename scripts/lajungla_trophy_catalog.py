"""Extract a player's private trophy catalog; author: matymeatboy.

Generated names, descriptions, XML and icons belong only in ignored user data.
No network requests or catalog publication are performed.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET

GRADES = {'P': 1, 'G': 2, 'S': 3, 'B': 4}


class CatalogError(ValueError):
    pass


def read_trp(path):
    data = Path(path).read_bytes()
    if len(data) < 64 or len(data) > 64*1024*1024:
        raise CatalogError('Tamaño TRP inválido')
    magic, version, size, count, entry_size = struct.unpack_from('>IIQII', data)
    if magic != 0xdca24d00 or version not in (1, 2, 3) or size != len(data) or entry_size != 64 or count > 1024 or 64+64*count > size:
        raise CatalogError('Cabecera TRP inválida')
    entries, ranges = {}, []
    for index in range(count):
        entry = data[64+index*64:128+index*64]
        try:
            name = entry[:32].split(b'\0')[0].decode('ascii')
        except UnicodeError as exc:
            raise CatalogError('Nombre TRP inválido') from exc
        if not name or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.' for c in name) or name in ('.', '..') or name.casefold() in {n.casefold() for n in entries}:
            raise CatalogError('Nombre TRP inseguro o duplicado')
        offset, length = struct.unpack_from('>QQ', entry, 32)
        if offset < 64+64*count or offset > size or length > size-offset or any(offset < b and a < offset+length for a, b in ranges):
            raise CatalogError('Intervalo TRP inválido')
        ranges.append((offset, offset+length))
        entries[name] = data[offset:offset+length]
    return entries


def _xml(data):
    if len(data) > 1024*1024 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise CatalogError('XML de trofeos no permitido')
    try:
        result = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CatalogError('XML de trofeos inválido') from exc
    if result.tag != 'trophyconf':
        raise CatalogError('Raíz de trofeos inválida')
    return result


def _records(root):
    result = {}
    try:
        for trophy in root.findall('trophy'):
            tid = int(trophy.attrib['id'])
            grade = GRADES[trophy.attrib['ttype']]
            pid = int(trophy.get('pid', '-1'))
            if tid in result or not 0 <= tid < 128 or pid < -1 or pid >= 128 or trophy.get('hidden') not in ('yes', 'no'):
                raise CatalogError('ID o atributos de trofeo inválidos')
            result[tid] = {'id': tid, 'grade': grade, 'hidden': trophy.get('hidden') == 'yes', 'pid': pid,
                           'name': trophy.findtext('name', ''), 'description': trophy.findtext('detail', ''),
                           'icon': f'icons/TROP{tid:03}.PNG'}
    except (ValueError, KeyError) as exc:
        raise CatalogError('Definición de trofeo inválida') from exc
    if not result:
        raise CatalogError('Catálogo sin trofeos')
    for trophy in result.values():
        if trophy['pid'] != -1 and (trophy['pid'] not in result or result[trophy['pid']]['grade'] != 1):
            raise CatalogError('Relación de platino inválida')
    return result


def extract_catalog(trp, communication_id='NPWR01344_00', language=1):
    if communication_id != 'NPWR01344_00':
        raise CatalogError('Este motor admite solamente NPWR01344_00')
    entries = read_trp(trp)
    if 'TROPCONF.SFM' not in entries:
        raise CatalogError('Falta TROPCONF.SFM')
    canonical = _records(_xml(entries['TROPCONF.SFM']))
    localized = _xml(entries.get(f'TROP_{language:02}.SFM', entries.get('TROP.SFM', entries['TROPCONF.SFM'])))
    records = _records(localized)
    if set(records) != set(canonical) or any(any(records[i][key] != canonical[i][key] for key in ('grade', 'hidden', 'pid')) for i in canonical):
        raise CatalogError('El catálogo traducido no coincide con los IDs originales')
    catalog = {'format': 1, 'communication_id': communication_id, 'title': localized.findtext('title-name', ''),
               'description': localized.findtext('title-detail', ''), 'trophies': [records[i] for i in sorted(records)]}
    return catalog, entries


def encode_catalog(catalog):
    data = bytearray(b'LJTRP01\0')
    def integer(value):
        data.extend(struct.pack('>I', value & 0xffffffff))
    def string(value, limit):
        encoded = value.encode('utf-8')
        if len(encoded) >= limit or '\0' in value:
            raise CatalogError('Texto de trofeo demasiado largo o inválido')
        integer(len(encoded))
        data.extend(encoded)
    integer(len(catalog['trophies']))
    string(catalog['communication_id'], 32)
    string(catalog['title'], 128)
    string(catalog['description'], 1024)
    for trophy in catalog['trophies']:
        for key in ('id', 'grade', 'hidden', 'pid'):
            integer(int(trophy[key]))
        string(trophy['name'], 128)
        string(trophy['description'], 1024)
        string(trophy['icon'], 128)
    return bytes(data)


def achievements_set(catalog, game_id='tokyojungle', version='>=0.1.0'):
    # PS3 native sets are explicitly supported by the upstream SDK SPEC.
    # Only actual platinum grades are omitted. Tokyo Jungle's id 0 is GOLD.
    return {'format': 1, 'game': game_id, 'source': 'native', 'console': 'ps3', 'versions': version,
            'achievements': [{'id': t['id'], 'native': t['id'], 'title': t['name'],
                              'description': t['description'], 'points': {2: 25, 3: 10, 4: 5}[t['grade']]}
                             for t in catalog['trophies'] if t['grade'] != 1]}


def prepare_catalog(trp, output, language=1):
    catalog, entries = extract_catalog(trp, language=language)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assets = {'catalog.bin': encode_catalog(catalog),
              'catalog.json': (json.dumps(catalog, ensure_ascii=False, indent=2)+'\n').encode(),
              'recompachievements.json': (json.dumps(achievements_set(catalog), ensure_ascii=False, indent=2)+'\n').encode()}
    for trophy in catalog['trophies']:
        name = Path(trophy['icon']).name
        if name in entries:
            assets[trophy['icon']] = entries[name]
    # Every output is replaced, never written through an existing hardlink.
    for name, value in assets.items():
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.trophy-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(value)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return catalog


def main():
    parser = argparse.ArgumentParser(description='Extrae metadatos privados de trofeos desde tu TROPHY.TRP')
    parser.add_argument('trp', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--language', type=int, default=1)
    args = parser.parse_args()
    try:
        catalog = prepare_catalog(args.trp, args.output, args.language)
    except (CatalogError, OSError) as exc:
        parser.exit(1, f'Error de trofeos: {exc}\n')
    print(f"Catálogo privado preparado: {len(catalog['trophies'])} trofeos; no se publicó contenido.")


if __name__ == '__main__':
    main()

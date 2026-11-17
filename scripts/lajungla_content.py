"""Tokyo Jungle PKG inspection and transactional installation. Author: matymeatboy.

PS3 PKG format follows the same header/table/AES-CTR layout used by
soyjxck/dod3-recomp src/install/pkg.cpp (MIT) and the original Tokyo Jungle
extractor. This implementation handles unaligned offsets and validates all
entries before writing. Game-specific DLC mounting is a separate step.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from Crypto.Cipher import AES

RETAIL_KEY = bytes.fromhex('2e7b71d7c9c9a14ea3221f188828b8f8')
TITLE_ID = 'NPUA80523'


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    offset: int
    size: int
    directory: bool


def safe_name(name):
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {
        f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10)}
    if (not name or '\\' in name or PurePosixPath(name).is_absolute()
            or any(not p or p in ('.', '..') or p.endswith((' ', '.'))
                   or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
                   or p.split('.')[0].upper() in reserved for p in parts)):
        raise PackageError(f'Ruta de paquete inválida: {name!r}')
    return name


class Package:
    def __init__(self, path):
        self.path = Path(path)
        actual = self.path.stat().st_size
        with self.path.open('rb') as stream:
            header = stream.read(0xc0)
        if len(header) != 0xc0:
            raise PackageError('Cabecera PKG truncada')
        magic, revision, kind = struct.unpack_from('>IHH', header)
        if (magic, revision, kind) != (0x7f504b47, 0x8000, 1):
            raise PackageError('Se necesita un PKG retail de PS3')
        count = struct.unpack_from('>I', header, 20)[0]
        total, self.data_offset, self.data_size = struct.unpack_from('>QQQ', header, 24)
        if (total != actual or self.data_offset < 0xc0
                or self.data_offset > total or self.data_size > total-self.data_offset
                or count > 1_000_000 or count*32 > self.data_size):
            raise PackageError('Tamaño o tabla PKG inválidos; comprueba el archivo completo')
        try:
            self.content_id = header[0x30:0x60].split(b'\0')[0].decode('ascii')
        except UnicodeError as exc:
            raise PackageError('Content ID inválido') from exc
        if not re.fullmatch(r'[A-Z]{2}\d{4}-NPUA80523_\d{2}-[A-Z0-9_]{16}', self.content_id):
            raise PackageError(f'Paquete incompatible con {TITLE_ID}: {self.content_id!r}')
        self.iv = int.from_bytes(header[0x70:0x80], 'big')
        table = self._read(0, count*32)
        self.entries = []
        seen = set()
        for i in range(count):
            no, ns, offset, size, flags, _ = struct.unpack_from('>IIQQII', table, i*32)
            if ns > 4096 or not ns:
                raise PackageError('Nombre PKG demasiado largo o vacío')
            try:
                name = self._read(no, ns).rstrip(b'\0').decode('utf-8')
            except UnicodeError as exc:
                raise PackageError('Nombre PKG no es UTF-8') from exc
            safe_name(name)
            folded = name.casefold()
            if folded in seen:
                raise PackageError(f'Entrada duplicada: {name}')
            seen.add(folded)
            self._bounds(offset, size)
            kind = flags & 255
            if kind not in (1, 2, 3, 4, 0x12):
                raise PackageError(f'Tipo de entrada desconocido: {kind}')
            self.entries.append(Entry(name, offset, size, kind in (4, 0x12)))
        files = {e.name.casefold() for e in self.entries if not e.directory}
        for e in self.entries:
            if any(str(p).casefold() in files for p in PurePosixPath(e.name).parents if str(p) != '.'):
                raise PackageError(f'Un archivo ocupa una carpeta: {e.name}')

    def _bounds(self, offset, size):
        if offset < 0 or size < 0 or offset > self.data_size or size > self.data_size-offset:
            raise PackageError('Entrada fuera de los datos PKG')

    def _read(self, offset, size):
        self._bounds(offset, size)
        skip = offset % 16
        with self.path.open('rb') as stream:
            stream.seek(self.data_offset + offset-skip)
            raw = stream.read(size+skip)
        if len(raw) != size+skip:
            raise PackageError('Datos PKG truncados')
        cipher = AES.new(RETAIL_KEY, AES.MODE_CTR, nonce=b'',
                         initial_value=self.iv + offset//16)
        return cipher.decrypt(raw)[skip:]

    def read(self, entry):
        return self._read(entry.offset, entry.size)


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install_package(path, root, progress=None):
    pkg = Package(path)  # Validate the full table before creating destinations.
    digest = sha256_file(path)
    root = Path(root).resolve()
    packages = root/'packages'
    final = packages/pkg.content_id
    if final.exists():
        try:
            manifest = json.loads((final/'manifest.json').read_text(encoding='utf-8'))
            if manifest['package_sha256'] == digest:
                for file in manifest['files']:
                    relative = safe_name(file['path'])
                    if sha256_file(final/'content'/relative) != file['sha256']:
                        raise PackageError('Instalación existente dañada; conserva una copia antes de repararla')
                return final
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise PackageError('Manifiesto existente inválido') from exc
        raise PackageError('Ya existe otro paquete con ese Content ID; no se reemplazó')
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.install-', dir=root))
    total = sum(e.size for e in pkg.entries if not e.directory)
    done = 0
    manifest = {'schema': 1, 'content_id': pkg.content_id, 'title_id': TITLE_ID,
                'package_sha256': digest, 'files': []}
    try:
        for e in pkg.entries:
            dest = stage/'content'/e.name
            if e.directory:
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            checksum = hashlib.sha256()
            with dest.open('xb') as out:
                for offset in range(0, e.size, 4*1024*1024):
                    block = pkg._read(e.offset+offset, min(4*1024*1024, e.size-offset))
                    out.write(block)
                    checksum.update(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
            manifest['files'].append({'path': e.name, 'size': e.size, 'sha256': checksum.hexdigest()})
        if sha256_file(path) != digest:
            raise PackageError('El paquete cambió durante la instalación; vuelve a intentarlo cuando termine de copiarse')
        (stage/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        packages.mkdir(exist_ok=True)
        os.rename(stage, final)
        return final
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description='Instala archivos propios de LaJungla sin mezclar partidas')
    parser.add_argument('package', type=Path)
    parser.add_argument('--root', type=Path, default=Path('game'))
    parser.add_argument('--inspect', action='store_true')
    args = parser.parse_args()
    if args.inspect:
        p = Package(args.package)
        print(json.dumps({'content_id': p.content_id, 'entries': len(p.entries)}, indent=2))
    else:
        print(install_package(args.package, args.root))


if __name__ == '__main__':
    main()

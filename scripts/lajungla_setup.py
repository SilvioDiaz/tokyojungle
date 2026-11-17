"""Transactional local Tokyo Jungle preparation. Author: matymeatboy.

Imports stay immutable under packages/CID/content. mounted is a disposable
copy, savedata is independent. RPCS3 is used only for authenticated EDAT files;
its private portable profile and license copies are removed after preparation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

from lajungla_content import PackageError, install_package, safe_name, sha256_file
from lajungla_self import SelfError, decrypt_self, rap_to_klicensee
from lajungla_trophy_catalog import CatalogError, prepare_catalog

# Published EDAT format constant, not a user's license.
EDAT_KEY0 = bytes.fromhex('be959ca8308defa2e5e180c63712a9ae')
EXPECTED_ELF_SHA256 = '6d253f6429485b43b816fd6884611377626ee95db5dd9200ea58395c93a0812d'


class SetupError(ValueError):
    pass


def _no_links(path):
    """Reject symlinks and Windows junctions before resolving any destination."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SetupError(f'No se permite un enlace o punto de reanálisis: {part}')
    return path


def _inventory(root):
    installed = []
    directory = root/'packages'
    if not directory.exists():
        return installed
    for item in sorted(directory.iterdir()):
        _no_links(item)
        if not item.is_dir():
            raise SetupError('Entrada inesperada en packages')
        manifest_path = _no_links(item/'manifest.json')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest['schema'] != 1 or manifest['content_id'] != item.name:
                raise SetupError('Identidad de manifiesto incompatible')
            files = []
            names = set()
            for entry in manifest['files']:
                name = safe_name(entry['path'])
                if name.casefold() in names:
                    raise SetupError('Ruta duplicada en manifiesto')
                names.add(name.casefold())
                source = _no_links(item/'content'/name)
                if not source.is_file() or sha256_file(source) != entry['sha256']:
                    raise SetupError(f'Contenido instalado alterado: {item.name}/{name}')
                files.append((name, source))
            installed.append((item.name, files, manifest))
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SetupError(f'Manifiesto de paquete inválido: {item.name}') from exc
    return installed


def _licenses(directory):
    directory = _no_links(directory)
    if not directory.is_dir():
        raise SetupError('La carpeta de licencias no existe')
    result = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() != '.rap':
            continue
        _no_links(path)
        value = path.read_bytes()
        if len(value) != 16:
            raise SetupError(f'La licencia RAP debe tener 16 bytes: {path.name}')
        result.append(value)
    return result


def _edat_license(path, licenses):
    with path.open('rb') as stream:
        header = stream.read(0xb0)
    if len(header) != 0xb0 or header[:4] != b'NPD\0':
        raise SetupError(f'Cabecera EDAT inválida: {path.name}')
    version, license_type = struct.unpack_from('>II', header, 4)
    flags = struct.unpack_from('>I', header, 0x80)[0]
    if (version, license_type, flags) != (3, 2, 0x3c):
        raise SetupError(f'Formato EDAT no compatible: {path.name}')
    try:
        cid = header[0x10:0x40].split(b'\0')[0].decode('ascii')
        safe_name(cid)
        if '/' in cid or not cid:
            raise ValueError()
    except (UnicodeError, ValueError) as exc:
        raise SetupError('Content ID EDAT inválido') from exc
    for rap in licenses:
        hkey = AES.new(EDAT_KEY0, AES.MODE_CBC, bytes(16)).decrypt(rap_to_klicensee(rap))
        mac = CMAC.new(hkey, header[:0xa0], ciphermod=AES)
        try:
            mac.verify(header[0xa0:0xb0])
        except ValueError:
            continue
        return cid, rap
    raise SetupError(f'Falta una licencia RAP válida para {cid}')


def _private_rpcs3(executable, directory):
    executable = _no_links(executable)
    if not executable.is_file():
        raise SetupError('No se encontró el ejecutable oficial de RPCS3')
    directory.mkdir()
    for source in executable.parent.iterdir():
        if source == executable or source.suffix.lower() == '.dll':
            shutil.copyfile(_no_links(source), directory/source.name)
    qt = executable.parent/'qt6'
    if qt.exists():
        for path in qt.rglob('*'):
            _no_links(path)
        shutil.copytree(qt, directory/'qt6')
    (directory/'portable.txt').write_text('', encoding='utf-8')
    return directory/executable.name


def _decrypt_edats(stage, licenses, executable, work):
    files = sorted(path for path in stage.rglob('*') if path.is_file() and path.suffix.lower() == '.edat')
    if not files:
        return
    matches = [(path, *_edat_license(path, licenses)) for path in files]
    tool = _private_rpcs3(executable, work/'rpcs3')
    exdata = tool.parent/'dev_hdd0/home/00000001/exdata'
    exdata.mkdir(parents=True)
    for _, cid, rap in matches:
        target = exdata/f'{cid}.rap'
        if target.exists() and target.read_bytes() != rap:
            raise SetupError(f'Licencias contradictorias para {cid}')
        target.write_bytes(rap)
    for path, _, _ in matches:
        output = path.with_name(path.name + '.unedat')
        if output.exists():
            raise SetupError(f'Conflicto con salida EDAT: {output.name}')
        try:
            result = subprocess.run([str(tool), '--headless', '--decrypt', str(path)],
                                    cwd=tool.parent, capture_output=True, timeout=120,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                    check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SetupError(f'RPCS3 no pudo descifrar {path.name}') from exc
        # Do not forward external logs: they may contain private license values.
        if result.returncode or not output.is_file() or output.stat().st_size == 0:
            raise SetupError(f'RPCS3 no pudo descifrar {path.name}')
        with output.open('rb') as stream:
            if stream.read(4) == b'NPD\0':
                raise SetupError(f'RPCS3 devolvió un EDAT todavía cifrado: {path.name}')
        os.replace(output, path)


def _elf(data, licenses):
    for key in [None, *(rap_to_klicensee(rap) for rap in licenses)]:
        try:
            result = decrypt_self(data, key)
        except SelfError:
            continue
        if (len(result) >= 64 and result[:6] == b'\x7fELF\x02\x02'
                and struct.unpack_from('>H', result, 18)[0] == 21
                and struct.unpack_from('>H', result, 52)[0] == 64):
            if hashlib.sha256(result).hexdigest() != EXPECTED_ELF_SHA256:
                raise SetupError('Versión del ELF incompatible con esta recompilación de Tokyo Jungle')
            return result
    raise SetupError('No se pudo obtener un ELF válido; comprueba las licencias del juego base')


def _mount_plan(installed):
    bases = [item for item in installed if any(name.casefold() == 'usrdir/eboot.bin' for name, _ in item[1])]
    if len(bases) != 1:
        raise SetupError('Se necesita exactamente un paquete base con USRDIR/EBOOT.BIN')
    base = bases[0]
    plan, occupied = [], set()
    for item in [base, *(item for item in installed if item is not base)]:
        for name, source in item[1]:
            lower = name.casefold()
            if item is not base:
                with source.open('rb') as stream:
                    magic = stream.read(4)
                if (source.suffix.lower() in {'.dll', '.exe', '.sprx', '.prx', '.self', '.elf'}
                        or magic in {b'SCE\0', b'\x7fELF'} or magic[:2] == b'MZ'
                        or Path(name).name.casefold() == 'eboot.bin'):
                    raise SetupError(f'El DLC contiene código que necesita recompilación: {name}')
                if not lower.startswith('usrdir/data/dlc/'):
                    if lower.startswith('usrdir/'):
                        raise SetupError(f'Ruta DLC no compatible: {name}')
                    continue  # PKG metadata is not a mounted DLC asset.
            if lower == '.lajungla' or lower.startswith('.lajungla/'):
                raise SetupError('El paquete ocupa una ruta reservada de preparación')
            if lower in occupied or any(p.as_posix().casefold() in occupied for p in Path(name).parents if str(p) != '.'):
                raise SetupError(f'Conflicto al montar contenido: {name}')
            if any(existing.startswith(lower+'/') for existing in occupied):
                raise SetupError(f'Conflicto al montar contenido: {name}')
            occupied.add(lower)
            plan.append((name, source))
    if 'eboot.elf' in occupied or '.lajungla-setup.json' in occupied:
        raise SetupError('El paquete ocupa una ruta reservada de preparación')
    return plan


def prepare(root, packages, licenses, rpcs3, elf_output=None):
    """Import additional PKGs and publish a checked mount, preserving savedata.

    Empty packages reuses all installed manifests. Successful package imports
    remain available after a later mount failure. Concurrent setup is refused.
    """
    root = _no_links(root)
    root.mkdir(parents=True, exist_ok=True)
    mounted = _no_links(root/'mounted')
    save = _no_links(root/'savedata')
    if save.exists() and not save.is_dir():
        raise SetupError('La ruta de partidas debe ser una carpeta')
    _no_links(root/'packages')
    export = _no_links(elf_output) if elf_output is not None else None
    if export and (export.name.casefold() == 'param.sfo' or export == root or export == root/'.setup.lock' or export.is_dir()
                   or export.is_relative_to(root/'packages')
                   or export.is_relative_to(mounted) or export.is_relative_to(save)):
        raise SetupError('La salida ELF debe estar fuera de paquetes, montaje y partidas')
    lock = root/'.setup.lock'
    _no_links(lock)
    try:
        handle = lock.open('x')
    except FileExistsError as exc:
        raise SetupError('Ya existe una preparación en curso (.setup.lock)') from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        # Validate previously imported paths before the installer follows them.
        _inventory(root)
        for package in packages:
            install_package(package, root)
        installed = _inventory(root)
        plan = _mount_plan(installed)
        if licenses is None:
            licenses = _no_links(root/'licenses')
            licenses.mkdir(exist_ok=True)
        raps = _licenses(licenses)
        identity = hashlib.sha256(json.dumps({'preparation': 2, 'packages': [item[2] for item in installed]}, sort_keys=True).encode()).hexdigest()
        marker = mounted/'.lajungla-setup.json'
        result = {'changed': False, 'mounted': str(mounted), 'elf': str(export or mounted/'EBOOT.ELF'),
                  'save_root': str(save), 'package_count': len(installed)}
        if marker.exists():
            _no_links(marker)
            try:
                previous = json.loads(marker.read_text(encoding='utf-8'))
                valid = (previous['identity'] == identity
                    and previous['files']['EBOOT.ELF'] == EXPECTED_ELF_SHA256) and all(
                    sha256_file(_no_links(mounted/safe_name(name))) == digest
                    for name, digest in previous['files'].items())
                sfo_name = next((name for name in previous['files'] if name.casefold() == 'param.sfo'), None)
                export_valid = export is None or (export.is_file() and sha256_file(export) == previous['files']['EBOOT.ELF']
                    and (sfo_name is None or sha256_file(_no_links(export.parent/'PARAM.SFO')) == previous['files'][sfo_name]))
                if valid and export_valid:
                    save.mkdir(exist_ok=True)
                    return result
            except (OSError, KeyError, ValueError, TypeError):
                pass  # Rebuild a disposable mount from verified originals.
        with tempfile.TemporaryDirectory(prefix='.prepare-', dir=root) as temporary:
            work = Path(temporary)
            stage = work/'mounted'
            stage.mkdir()
            for name, source in plan:
                target = stage/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            eboot = next(source for name, source in plan if name.casefold() == 'usrdir/eboot.bin')
            (stage/'EBOOT.ELF').write_bytes(_elf(eboot.read_bytes(), raps))
            _decrypt_edats(stage, raps, rpcs3, work)
            trophy = stage/'TROPDIR'/'NPWR01344_00'/'TROPHY.TRP'
            if trophy.exists():
                for language, number in [('en', 1), ('es', 3), ('fr', 2), ('pt', 17)]:
                    prepare_catalog(trophy, stage/'.lajungla'/'trophies'/language, language=number)
            hashes = {path.relative_to(stage).as_posix(): sha256_file(path)
                      for path in stage.rglob('*') if path.is_file()}
            (stage/'.lajungla-setup.json').write_text(json.dumps({'schema': 1, 'identity': identity, 'files': hashes}, indent=2), encoding='utf-8')
            old = work/'previous-mounted'
            exports = []
            try:
                if export:
                    export.parent.mkdir(parents=True, exist_ok=True)
                    outputs = [(export, stage/'EBOOT.ELF')]
                    sfo = next((stage/name for name, _ in plan if name.casefold() == 'param.sfo'), None)
                    if sfo is not None:
                        outputs.append((_no_links(export.parent/'PARAM.SFO'), sfo))
                    for index, (target, source) in enumerate(outputs):
                        if target.is_dir():
                            raise SetupError('Una carpeta ocupa una salida de preparación')
                        fd, name = tempfile.mkstemp(prefix='.lajungla-export-', dir=target.parent)
                        os.close(fd)
                        temporary_output = Path(name)
                        backup = work/f'previous-export-{index}' if target.exists() else None
                        exports.append((target, temporary_output, backup))
                        shutil.copyfile(source, temporary_output)
                        if backup:
                            shutil.copyfile(target, backup)
                if mounted.exists():
                    os.replace(mounted, old)
                published = []
                try:
                    for target, temporary_output, backup in exports:
                        os.replace(temporary_output, target)
                        published.append((target, backup))
                    os.replace(stage, mounted)
                except BaseException:
                    if old.exists():
                        os.replace(old, mounted)
                    for target, backup in reversed(published):
                        if backup:
                            shutil.copyfile(backup, target)
                        elif target.exists():
                            target.unlink()
                    raise
            finally:
                for _, temporary_output, _ in exports:
                    if temporary_output.exists():
                        temporary_output.unlink()
        save.mkdir(exist_ok=True)
        result['changed'] = True
        return result
    except (PackageError, SelfError, CatalogError, OSError) as exc:
        raise SetupError(str(exc)) from exc
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepara tu copia local de Tokyo Jungle sin modificar los paquetes originales')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--licenses', type=Path, help='Carpeta RAP; por defecto ROOT/licenses')
    parser.add_argument('--rpcs3', type=Path, required=True)
    parser.add_argument('--elf-output', type=Path)
    parser.add_argument('--package', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    try:
        result = prepare(args.root, args.package, args.licenses, args.rpcs3, args.elf_output)
    except (SetupError, PackageError) as exc:
        parser.exit(1, f'Error de preparación: {exc}\n')
    print('Contenido preparado.' if result['changed'] else 'Contenido ya preparado; sin cambios.')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

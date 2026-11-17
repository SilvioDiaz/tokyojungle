"""Fixtures synthétiques; ningún archivo del juego forma parte de estas pruebas."""
import hashlib
import struct
import sys
from pathlib import Path

import pytest
from Crypto.Cipher import AES

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lajungla_content import PackageError, Package, install_package

KEY = bytes.fromhex('2e7b71d7c9c9a14ea3221f188828b8f8')
CID = 'UP9000-NPUA80523_00-SYNTHETICTEST000'


def make_pkg(path, entries=None, content_id=CID, entry_type=3):
    entries = entries or [('USRDIR/a.txt', b'hello'), ('PARAM.SFO', b'fixture')]
    data = bytearray(32 * len(entries))
    records = []
    for name, payload in entries:
        name = name.encode()
        no = len(data)
        data += name
        po = len(data)
        data += payload
        records.append((no, len(name), po, len(payload), entry_type, 0))
    for i, record in enumerate(records):
        struct.pack_into('>IIQQII', data, i * 32, *record)
    header = bytearray(0x180)
    struct.pack_into('>IHHIIIIQQQ', header, 0, 0x7f504b47, 0x8000, 1,
                     0xc0, 0, 0, len(entries), 0x180 + len(data), 0x180, len(data))
    header[0x30:0x30+len(content_id)] = content_id.encode()
    iv = bytes(range(16))
    header[0x70:0x80] = iv
    path.write_bytes(header + AES.new(KEY, AES.MODE_CTR, nonce=b'',
                                     initial_value=int.from_bytes(iv, 'big')).encrypt(data))
    return path


def test_reads_unaligned_names_and_data(tmp_path):
    pkg = Package(make_pkg(tmp_path/'good.pkg'))
    assert pkg.content_id == CID
    assert pkg.read(pkg.entries[0]) == b'hello'
    assert pkg.read(pkg.entries[1]) == b'fixture'


def test_preserves_npdrm_data_entries(tmp_path):
    pkg = Package(make_pkg(tmp_path/'edat.pkg', [('USRDIR/test.edat', b'opaque')], entry_type=2))
    assert pkg.read(pkg.entries[0]) == b'opaque'
    assert not pkg.entries[0].directory


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape',
                                  'USRDIR/../../escape', 'USRDIR\\..\\escape',
                                  'USRDIR/x:stream', 'USRDIR/CON', 'USRDIR/trailing.'])
def test_rejects_unsafe_names_before_writing(tmp_path, name):
    with pytest.raises(PackageError):
        install_package(make_pkg(tmp_path/'bad.pkg', [(name, b'bad')]), tmp_path/'install')
    assert not (tmp_path/'install'/'packages').exists()


def test_rejects_truncation(tmp_path):
    p = make_pkg(tmp_path/'bad.pkg')
    p.write_bytes(p.read_bytes()[:-1])
    with pytest.raises(PackageError):
        Package(p)


def test_rejects_other_region(tmp_path):
    with pytest.raises(PackageError):
        Package(make_pkg(tmp_path/'eu.pkg', content_id='EP9000-NPEA00421_00-SYNTHETICTEST0001'))


def test_rejects_case_collisions(tmp_path):
    with pytest.raises(PackageError):
        Package(make_pkg(tmp_path/'bad.pkg', [('A', b'a'), ('a', b'b')]))


def test_install_is_idempotent_and_keeps_saves(tmp_path):
    root = tmp_path/'install'
    (root/'savedata').mkdir(parents=True)
    (root/'savedata'/'save').write_bytes(b'progress')
    p = make_pkg(tmp_path/'good.pkg')
    first = install_package(p, root)
    second = install_package(p, root)
    assert first == second
    assert (first/'content'/'USRDIR'/'a.txt').read_bytes() == b'hello'
    assert (first/'manifest.json').is_file()
    assert (root/'savedata'/'save').read_bytes() == b'progress'


def test_failed_install_does_not_publish(tmp_path):
    def cancel(done, total):
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        install_package(make_pkg(tmp_path/'good.pkg'), tmp_path/'install', progress=cancel)
    packages = tmp_path/'install'/'packages'
    assert not packages.exists() or list(packages.iterdir()) == []


def test_changed_package_never_replaces_existing(tmp_path):
    root = tmp_path/'install'
    first = install_package(make_pkg(tmp_path/'one.pkg'), root)
    make_pkg(tmp_path/'two.pkg', [('USRDIR/a.txt', b'changed')])
    with pytest.raises(PackageError):
        install_package(tmp_path/'two.pkg', root)
    assert (first/'content'/'USRDIR'/'a.txt').read_bytes() == b'hello'


def test_source_changed_during_install_is_not_published(tmp_path):
    source = make_pkg(tmp_path/'changing.pkg')
    changed = False
    def mutate(done, total):
        nonlocal changed
        if not changed:
            data = bytearray(source.read_bytes())
            data[-1] ^= 1
            source.write_bytes(data)
            changed = True
    with pytest.raises(PackageError, match='cambi'):
        install_package(source, tmp_path/'install', progress=mutate)
    packages = tmp_path/'install'/'packages'
    assert not packages.exists() or not list(packages.iterdir())

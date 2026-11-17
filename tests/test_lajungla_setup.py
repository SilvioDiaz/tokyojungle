"""Synthetic setup transactions; author: matymeatboy. No real game assets."""
import hashlib
import struct
import sys
from pathlib import Path

import pytest
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import lajungla_setup as setup
from test_lajungla_content import make_pkg

BASE = 'UP9000-NPUA80523_00-BASEFIXTURE00000'
DLC = 'UP9000-NPUA80523_00-DLCFIXTURE000000'
ELF = bytearray(b'\x7fELF\x02\x02' + bytes(58))
struct.pack_into('>H', ELF, 18, 21)
struct.pack_into('>H', ELF, 52, 64)
ELF = bytes(ELF)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    base = make_pkg(tmp_path/'base.pkg', [('USRDIR/EBOOT.BIN', b'synthetic-self'),
                    ('USRDIR/data/base', b'base'), ('PARAM.SFO', b'synthetic-sfo')], content_id=BASE)
    licenses = tmp_path/'licenses'
    licenses.mkdir()
    tool = tmp_path/'tool'/'rpcs3.exe'
    tool.parent.mkdir()
    tool.write_bytes(b'never executed')
    monkeypatch.setattr(setup, 'decrypt_self', lambda data, key=None: ELF)
    monkeypatch.setattr(setup, 'EXPECTED_ELF_SHA256', hashlib.sha256(ELF).hexdigest())
    return tmp_path/'game', base, licenses, tool


def test_initial_then_identity_noop_and_separate_saves(inputs):
    root, base, licenses, tool = inputs
    result = setup.prepare(root, [base], licenses, tool)
    mounted = root/'mounted'
    assert (mounted/'USRDIR/data/base').read_bytes() == b'base'
    assert (mounted/'EBOOT.ELF').read_bytes() == ELF
    assert result['changed'] is True
    (root/'savedata'/'slot').write_bytes(b'private save')
    before = (mounted/'EBOOT.ELF').stat().st_mtime_ns
    result = setup.prepare(root, [base], licenses, tool)
    assert result['changed'] is False
    assert (mounted/'EBOOT.ELF').stat().st_mtime_ns == before
    assert (root/'savedata'/'slot').read_bytes() == b'private save'


def test_incremental_dlc_and_original_protection(inputs, tmp_path):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    dlc = make_pkg(tmp_path/'dlc.pkg', [('USRDIR/data/dlc/animal', b'animal')], content_id=DLC)
    assert setup.prepare(root, [dlc], licenses, tool)['changed']
    (root/'mounted/USRDIR/data/base').write_bytes(b'consumer changed it')
    assert (root/'packages'/BASE/'content/USRDIR/data/base').read_bytes() == b'base'
    assert (root/'mounted/USRDIR/data/dlc/animal').read_bytes() == b'animal'


@pytest.mark.parametrize('name', ['USRDIR/data/dlc/base', 'USRDIR/plugin.sprx', 'USRDIR/data/dlc/code.dll'])
def test_conflicts_and_executable_dlc_keep_old_mount(inputs, tmp_path, name):
    root, base, licenses, tool = inputs
    if name.endswith('/base'):
        base = make_pkg(base, [('USRDIR/EBOOT.BIN', b'self'),
                              ('USRDIR/data/dlc/base', b'original')], content_id=BASE)
    setup.prepare(root, [base], licenses, tool)
    dlc = make_pkg(tmp_path/'dlc.pkg', [(name, b'new')], content_id=DLC)
    with pytest.raises(setup.SetupError):
        setup.prepare(root, [dlc], licenses, tool)
    assert not (root/'mounted'/name).exists() or (root/'mounted'/name).read_bytes() == b'original'
    assert (root/'mounted/EBOOT.ELF').read_bytes() == ELF


def edat(rap, cid=DLC):
    header = bytearray(0xb0)
    header[:4] = b'NPD\0'
    struct.pack_into('>II', header, 4, 3, 2)
    header[0x10:0x10+len(cid)] = cid.encode()
    struct.pack_into('>I', header, 0x80, 0x3c)
    key = AES.new(setup.EDAT_KEY0, AES.MODE_CBC, bytes(16)).decrypt(setup.rap_to_klicensee(rap))
    header[0xa0:0xb0] = CMAC.new(key, bytes(header[:0xa0]), ciphermod=AES).digest()
    return bytes(header)


def test_license_matching_ignores_filename_and_external_decrypt_is_atomic(inputs, tmp_path, monkeypatch):
    root, base, licenses, tool = inputs
    rap = bytes(range(16))
    (licenses/'arbitrary.rap').write_bytes(rap)
    encrypted = edat(rap)
    dlc = make_pkg(tmp_path/'dlc.pkg', [('USRDIR/data/dlc/a.edat', encrypted)], content_id=DLC)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if setup.os.name == 'nt':
            assert kwargs['creationflags'] == setup.subprocess.CREATE_NO_WINDOW
        exe, _, _, source = command
        assert (Path(exe).parent/'dev_hdd0/home/00000001/exdata'/f'{DLC}.rap').read_bytes() == rap
        Path(source + '.unedat').write_bytes(b'decrypted')
        return type('Completed', (), {'returncode': 0})()
    monkeypatch.setattr(setup.subprocess, 'run', run)
    setup.prepare(root, [base, dlc], licenses, tool)
    assert len(calls) == 1
    assert (root/'mounted/USRDIR/data/dlc/a.edat').read_bytes() == b'decrypted'
    assert (root/'packages'/DLC/'content/USRDIR/data/dlc/a.edat').read_bytes() == encrypted
    assert not (tool.parent/'dev_hdd0').exists()


def test_decrypt_failure_rolls_back_mount_and_preserves_saves(inputs, tmp_path, monkeypatch):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    (root/'savedata/slot').write_bytes(b'save')
    (licenses/'x.rap').write_bytes(bytes(16))
    dlc = make_pkg(tmp_path/'dlc.pkg', [('USRDIR/data/dlc/a.edat', edat(bytes(16)))], content_id=DLC)
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **k: type('Done', (), {'returncode': 1})())
    with pytest.raises(setup.SetupError, match='RPCS3'):
        setup.prepare(root, [dlc], licenses, tool)
    assert (root/'mounted/EBOOT.ELF').read_bytes() == ELF
    assert not (root/'mounted/USRDIR/data/dlc/a.edat').exists()
    assert (root/'savedata/slot').read_bytes() == b'save'
    assert not list(root.glob('.prepare-*'))


def test_invalid_elf_does_not_replace_mount(inputs, monkeypatch):
    root, base, licenses, tool = inputs
    monkeypatch.setattr(setup, 'decrypt_self', lambda *args: b'bad')
    with pytest.raises(setup.SetupError, match='ELF'):
        setup.prepare(root, [base], licenses, tool)
    assert not (root/'mounted').exists()


def test_other_valid_ppu_elf_version_keeps_previous_mount(inputs, monkeypatch):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    old_marker = root/'mounted/.lajungla-setup.json'
    old_marker.unlink()  # Force preparation through the decoder again.
    other_version = ELF + b'different game revision'
    monkeypatch.setattr(setup, 'decrypt_self', lambda *args: other_version)
    with pytest.raises(setup.SetupError, match='Versión del ELF incompatible'):
        setup.prepare(root, [], licenses, tool)
    assert (root/'mounted/EBOOT.ELF').read_bytes() == ELF


def test_symlink_mount_rejected(inputs, tmp_path):
    root, base, licenses, tool = inputs
    root.mkdir()
    outside = tmp_path/'outside'
    outside.mkdir()
    try:
        (root/'mounted').symlink_to(outside, target_is_directory=True)
    except OSError:
        # Directory junctions need no Windows developer mode/admin rights.
        result = setup.subprocess.run(['cmd', '/c', 'mklink', '/J', str(root/'mounted'), str(outside)],
                                      capture_output=True)
        assert result.returncode == 0
    try:
        with pytest.raises(setup.SetupError, match='enlace'):
            setup.prepare(root, [base], licenses, tool)
        assert not list(outside.iterdir())
    finally:
        (root/'mounted').rmdir()


def test_empty_import_reuses_installed_manifests_and_exports_elf(inputs, tmp_path):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    export = tmp_path/'output/EBOOT.ELF'
    setup.prepare(root, [], licenses, tool, export)
    assert export.read_bytes() == ELF
    assert (export.parent/'PARAM.SFO').read_bytes() == b'synthetic-sfo'
    assert not setup.prepare(root, [], licenses, tool, export)['changed']


def test_publication_failure_restores_previous_mount_and_elf(inputs, tmp_path, monkeypatch):
    root, base, licenses, tool = inputs
    export = tmp_path/'EBOOT.ELF'
    setup.prepare(root, [base], licenses, tool, export)
    export.write_bytes(b'previous export')
    (export.parent/'PARAM.SFO').write_bytes(b'previous sfo')
    dlc = make_pkg(tmp_path/'dlc.pkg', [('USRDIR/data/dlc/animal', b'animal')], content_id=DLC)
    replace = setup.os.replace
    def fail_stage(source, target):
        if Path(source).name == 'mounted' and Path(source).parent.name.startswith('.prepare-'):
            raise OSError('synthetic publication failure')
        return replace(source, target)
    monkeypatch.setattr(setup.os, 'replace', fail_stage)
    with pytest.raises(setup.SetupError, match='publication failure'):
        setup.prepare(root, [dlc], licenses, tool, export)
    assert export.read_bytes() == b'previous export'
    assert (export.parent/'PARAM.SFO').read_bytes() == b'previous sfo'
    assert (root/'mounted/EBOOT.ELF').read_bytes() == ELF
    assert not (root/'mounted/USRDIR/data/dlc/animal').exists()


def test_missing_license_rolls_back_before_external_tool(inputs, tmp_path, monkeypatch):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    dlc = make_pkg(tmp_path/'dlc.pkg', [('USRDIR/data/dlc/a.edat', edat(bytes(16)))], content_id=DLC)
    def forbidden(*args, **kwargs):
        pytest.fail('RPCS3 must not run without authenticated license')
    monkeypatch.setattr(setup.subprocess, 'run', forbidden)
    with pytest.raises(setup.SetupError, match='Falta una licencia'):
        setup.prepare(root, [dlc], licenses, tool)
    assert (root/'mounted/EBOOT.ELF').read_bytes() == ELF


def test_modified_original_refused_on_noop(inputs):
    root, base, licenses, tool = inputs
    setup.prepare(root, [base], licenses, tool)
    (root/'packages'/BASE/'content/USRDIR/data/base').write_bytes(b'tampered')
    with pytest.raises(setup.SetupError, match='alterado'):
        setup.prepare(root, [], licenses, tool)
    assert (root/'mounted/USRDIR/data/base').read_bytes() == b'base'


def test_reparse_point_mount_rejected_without_admin(inputs, tmp_path):
    root, base, licenses, tool = inputs
    root.mkdir()
    outside = tmp_path/'outside'
    outside.mkdir()
    command = ['cmd', '/c', 'mklink', '/J', str(root/'mounted'), str(outside)]
    result = setup.subprocess.run(command, capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(setup.SetupError, match='enlace'):
            setup.prepare(root, [base], licenses, tool)
        assert not list(outside.iterdir())
    finally:
        (root/'mounted').rmdir()  # Remove the junction itself, never its target.


def test_conflicting_setup_lock_refuses_changes(inputs):
    root, base, licenses, tool = inputs
    root.mkdir()
    (root/'.setup.lock').write_text('another process')
    with pytest.raises(setup.SetupError, match='en curso'):
        setup.prepare(root, [base], licenses, tool)
    assert not (root/'packages').exists()


def test_cli_reports_spanish_error_without_secret_values(inputs, capsys):
    root, base, licenses, tool = inputs
    with pytest.raises(SystemExit) as error:
        setup.main(['--root', str(root), '--licenses', str(licenses), '--rpcs3', str(tool)])
    assert error.value.code == 1
    assert 'paquete base' in capsys.readouterr().err


def test_cli_optional_license_folder_and_success(inputs, capsys):
    root, base, _, tool = inputs
    assert setup.main(['--root', str(root), '--package', str(base), '--rpcs3', str(tool)]) == 0
    assert (root/'licenses').is_dir()
    assert 'Contenido preparado.' in capsys.readouterr().out


def test_wrong_license_authentication_never_calls_tool(inputs, tmp_path, monkeypatch):
    root, base, licenses, tool = inputs
    (licenses/'wrong-name.rap').write_bytes(bytes(16))
    dlc = make_pkg(tmp_path/'finished.pkg.crdownload',
                   [('USRDIR/data/dlc/a.edat', edat(bytes(range(16))))], content_id=DLC)
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **kw: pytest.fail('unauthenticated EDAT'))
    with pytest.raises(setup.SetupError, match='Falta una licencia'):
        setup.prepare(root, [base, dlc], licenses, tool)
    assert not (root/'mounted').exists()
    assert (root/'packages'/DLC/'content/USRDIR/data/dlc/a.edat').exists()


def test_trophy_conversion_failure_keeps_previous_mount_and_save(inputs, tmp_path, monkeypatch):
    import lajungla_trophy_catalog as converter
    root, base, licenses, tool = inputs
    package = make_pkg(tmp_path/'with-trophies.pkg', [
        ('USRDIR/EBOOT.BIN', b'synthetic-self'),
        ('TROPDIR/NPWR01344_00/TROPHY.TRP', b'fixture')], content_id=BASE)
    def convert(source, output, language):
        output.mkdir(parents=True)
        (output/'catalog.bin').write_bytes(bytes([language]))
    monkeypatch.setattr(setup, 'prepare_catalog', convert)
    setup.prepare(root, [package], licenses, tool)
    (root/'savedata'/'slot').write_bytes(b'preserve progress')
    mounted = root/'mounted'
    marker = (mounted/'.lajungla-setup.json').read_bytes()
    # Broken disposable output forces regeneration, whose conversion then fails.
    (mounted/'.lajungla/trophies/es/catalog.bin').write_bytes(b'damaged metadata')
    def fail(*args, **kwargs):
        raise converter.CatalogError('invalid trophy archive')
    monkeypatch.setattr(setup, 'prepare_catalog', fail)
    with pytest.raises(setup.SetupError, match='invalid trophy archive'):
        setup.prepare(root, [], licenses, tool)
    assert (mounted/'.lajungla-setup.json').read_bytes() == marker
    assert (mounted/'EBOOT.ELF').read_bytes() == ELF
    assert (root/'savedata'/'slot').read_bytes() == b'preserve progress'


def test_package_cannot_replace_private_generated_metadata(inputs, tmp_path):
    root, _, licenses, tool = inputs
    package = make_pkg(tmp_path/'reserved.pkg', [('USRDIR/EBOOT.BIN', b'synthetic-self'),
                       ('.lajungla/trophies/es/catalog.bin', b'untrusted')], content_id=BASE)
    with pytest.raises(setup.SetupError, match='reservada'):
        setup.prepare(root, [package], licenses, tool)
    assert not (root/'mounted').exists()

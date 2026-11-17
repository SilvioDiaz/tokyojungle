"""Offline archive verification/bundling tests; no SDL download is required."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def ps_quote(value):
    return "'"+str(value).replace("'","''")+"'"


def test_sdl_bundle_checks_hash_and_copies_license():
    with tempfile.TemporaryDirectory(prefix='tj-sdl-bundle-') as directory:
        directory=Path(directory)
        archive=directory/'runtime.zip'
        with zipfile.ZipFile(archive,'w') as zipped:
            zipped.writestr('SDL2.dll',b'fixture DLL')
            zipped.writestr('README-SDL.txt',b'fixture redistribution notice')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        script=ROOT/'scripts/tj_bundle_sdl2.ps1'
        common=f"$ErrorActionPreference='Stop'; . {ps_quote(script)}; "
        command=common+f'Copy-TjSdlRuntime -Archive {ps_quote(archive)} -CacheDirectory {ps_quote(directory/"cache")} -Destination {ps_quote(directory/"engine")} -ExpectedSha256 {ps_quote(digest)}'
        subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True)
        assert (directory/'engine/SDL2.dll').read_bytes()==b'fixture DLL'
        assert (directory/'engine/README-SDL.txt').read_bytes()==b'fixture redistribution notice'
        assert (directory/'engine/SDL2-LICENSE.txt').read_bytes()==(ROOT/'licenses/SDL2.txt').read_bytes()
        command=common+f'try {{ Copy-TjSdlRuntime -Archive {ps_quote(archive)} -CacheDirectory {ps_quote(directory/"badcache")} -Destination {ps_quote(directory/"badengine")} -ExpectedSha256 {ps_quote("0"*64)} }} catch {{ exit 17 }}'
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',command])
        assert result.returncode==17
        assert not (directory/'badengine').exists()

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_support', ROOT / 'scripts/build_support.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_windows_environment_merges_path_case_insensitively(self):
        result = SimpleNamespace(returncode=0, stdout='Path=C:\\MSVC\\bin\n', stderr='')
        tools = {'vcvars': Path('C:/VS/vcvars64.bat'), 'compiler': Path('C:/LLVM/bin/clang-cl.exe')}
        with patch.dict(build.os.environ, {'PATH': 'old'}, clear=True), patch.object(build.subprocess, 'run', return_value=result):
            env = build.build_environment(tools)
        self.assertEqual([key for key in env if key.lower() == 'path'], ['PATH'])
        self.assertIn('MSVC', env['PATH'])
        self.assertIn('LLVM', env['PATH'])

    def test_wrong_elf_rejects_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input').mkdir()
            elf = root / 'input/EBOOT.ELF'
            elf.write_bytes(b'wrong ELF')
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                build.validate_elf(root, {'input_elf_sha256': '0' * 64})
            self.assertEqual(elf.read_bytes(), b'wrong ELF')

    def test_tools_with_spaces_and_argument_lists(self):
        with tempfile.TemporaryDirectory(prefix='tool paths ') as directory:
            root = Path(directory)
            vs = root / 'Visual Studio Build Tools'
            llvm = root / 'LLVM Tools'
            for path in [vs / 'VC/Auxiliary/Build/vcvars64.bat',
                         vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe',
                         vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe',
                         llvm / 'bin/clang-cl.exe']:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            tools = build.select_tools(vs, llvm)
            configure, compile_ = build.cmake_commands(root, root / 'build dir', root / 'runtime dir', tools, 99)
            self.assertEqual(configure[0], tools['cmake'])
            self.assertIn('-DCMAKE_C_COMPILER=' + str(llvm / 'bin/clang-cl.exe'), configure)
            self.assertIn(root / 'build dir', configure)
            self.assertIn('-DTJ_ENABLE_SPU=ON', configure)
            self.assertEqual(compile_[-1], '6')
            shell = build.vcvars_command(tools['vcvars'])
            self.assertEqual(shell, f'cmd.exe /d /s /c ""{tools["vcvars"]}" >nul && set"')

    def test_generated_digest_detects_modified_and_missing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / 'generated'
            generated.mkdir()
            source = generated / 'ppu_recomp_000.cpp'
            source.write_text('original')
            first = build.generated_digest(root)
            (generated / '.lajungla-generation.json').write_text('stamp is excluded')
            self.assertEqual(build.generated_digest(root), first)
            source.write_text('changed')
            self.assertNotEqual(build.generated_digest(root), first)
            source.unlink()
            self.assertNotEqual(build.generated_digest(root), first)

    def fixture_runtime(self, directory):
        root = Path(directory) / 'game'
        root.mkdir()
        runtime = root.parent / 'ps3recomp'
        runtime.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(runtime), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init', '-q')
        git('config', 'core.autocrlf', 'false')
        (runtime / 'tracked.txt').write_text('one\n')
        git('add', '.')
        git('-c', 'user.name=Build Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base')
        commit = git('rev-parse', 'HEAD')
        patches = []
        for index, (old, new) in enumerate([('one', 'two'), ('two', 'three')]):
            text = ('diff --git a/tracked.txt b/tracked.txt\n'
                    '--- a/tracked.txt\n+++ b/tracked.txt\n@@ -1 +1 @@\n'
                    f'-{old}\n+{new}\n')
            path = root / f'patch{index}.patch'
            path.write_text(text)
            patches.append({'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        lock = {'runtime': {'repository': 'unused-invalid', 'commit': commit, 'patches': patches}}
        return root, runtime, lock

    def test_ordered_overlapping_patches_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root, runtime, lock = self.fixture_runtime(directory)
            build.prepare_runtime(root, lock)
            self.assertEqual((runtime / 'tracked.txt').read_text(), 'three\n')
            first = build.checkout_state(runtime)
            build.prepare_runtime(root, lock)
            self.assertEqual(build.checkout_state(runtime), first)

    def test_dirty_checkout_preserved_without_applying_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            root, runtime, lock = self.fixture_runtime(directory)
            (runtime / 'tracked.txt').write_text('local changes\n')
            extra = runtime / 'personal.txt'
            extra.write_text('preserve me\n')
            before = build.checkout_state(runtime)
            with self.assertRaisesRegex(RuntimeError, 'Existing checkout preserved'):
                build.prepare_runtime(root, lock)
            self.assertEqual(build.checkout_state(runtime), before)
            self.assertEqual(extra.read_text(), 'preserve me\n')

    def test_wrong_patch_hash_does_not_touch_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root, runtime, lock = self.fixture_runtime(directory)
            lock['runtime']['patches'][0]['sha256'] = '0' * 64
            before = build.checkout_state(runtime)
            with self.assertRaisesRegex(RuntimeError, 'Patch hash mismatch'):
                build.prepare_runtime(root, lock)
            self.assertEqual(build.checkout_state(runtime), before)


if __name__ == '__main__':
    unittest.main()

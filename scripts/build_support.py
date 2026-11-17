#!/usr/bin/env python3
"""Reproduce the pinned Windows build without changing global tool settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, *, cwd=None, env=None, capture=False):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                            capture_output=capture, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip() if capture else ''
        raise RuntimeError(f'Command failed ({result.returncode}): {subprocess.list2cmdline(list(map(str, args)))}\n{detail}')
    return result.stdout if capture else ''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_elf(root, lock):
    path = root / 'input/EBOOT.ELF'
    if not path.is_file() or sha256(path) != lock['input_elf_sha256'].lower():
        raise RuntimeError('Provide the verified decrypted input/EBOOT.ELF from your game; ELF SHA256 does not match dependencies.lock.json')


def checkout_state(path):
    # Git canonicalizes tracked text according to the checkout's attributes.
    diff = run(['git', '-C', path, 'diff', '--no-ext-diff', '--binary', 'HEAD'], capture=True)
    others = run(['git', '-C', path, 'ls-files', '--others', '--exclude-standard', '-z'], capture=True)
    untracked = {}
    for name in filter(None, others.split('\0')):
        untracked[name] = run(['git', '-C', path, 'hash-object', '--path=' + name, '--', name], capture=True).strip()
    return diff, untracked


def prepare_runtime(root, lock):
    runtime = root.parent / 'ps3recomp'
    spec = lock['runtime']
    patches = []
    for entry in spec['patches']:
        patch = root / entry['path']
        if sha256(patch) != entry['sha256'].lower():
            raise RuntimeError(f'Patch hash mismatch: {patch}')
        patches.append(patch)
    if not runtime.exists():
        run(['git', 'clone', '--no-checkout', spec['repository'], runtime])
        run(['git', '-C', runtime, 'checkout', '--detach', spec['commit']])
    head = run(['git', '-C', runtime, 'rev-parse', 'HEAD'], capture=True).strip()
    if head != spec['commit']:
        raise RuntimeError(f'Runtime HEAD is {head}; expected {spec["commit"]}. Existing checkout preserved.')
    active = checkout_state(runtime)
    # Construct each allowed patch prefix in an isolated clone. Overlapping
    # patches cannot safely be recognized by reversing the first in place.
    matched = None
    with tempfile.TemporaryDirectory(prefix='lajungla-runtime-') as directory:
        reference = Path(directory) / 'reference'
        run(['git', 'clone', '--quiet', '--shared', '--no-checkout', runtime, reference], capture=True)
        run(['git', '-C', reference, 'checkout', '--quiet', '--detach', spec['commit']], capture=True)
        if checkout_state(reference) == active:
            matched = 0
        for index, patch in enumerate(patches, 1):
            run(['git', '-C', reference, 'apply', '--check', patch], capture=True)
            run(['git', '-C', reference, 'apply', patch], capture=True)
            if checkout_state(reference) == active:
                matched = index
    if matched is None:
        raise RuntimeError('Runtime has unrelated or modified local changes. Existing checkout preserved; no reset, clean, or patch applied.')
    for patch in patches[matched:]:
        run(['git', '-C', runtime, 'apply', '--check', patch], capture=True)
        run(['git', '-C', runtime, 'apply', patch], capture=True)
    print(f'Runtime verified: {head}, {len(patches)} locked patches')
    return runtime


def select_tools(installation, llvm):
    installation, llvm = Path(installation), Path(llvm)
    tools = {
        'vcvars': installation / 'VC/Auxiliary/Build/vcvars64.bat',
        'cmake': installation / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe',
        'ninja': installation / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe',
        'compiler': llvm / 'bin/clang-cl.exe',
    }
    for name, path in tools.items():
        if not path.is_file():
            raise RuntimeError(f'Missing {name}: {path}')
    return tools


def discover_tools():
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        raise RuntimeError('Visual Studio Installer vswhere.exe not found; install Visual Studio Build Tools with C++ tools')
    installation = run([vswhere, '-latest', '-products', '*', '-requires',
                        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                        '-property', 'installationPath'], capture=True).strip()
    if not installation:
        raise RuntimeError('No Visual Studio installation with C++ build tools found')
    llvm = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'LLVM'
    return select_tools(installation, llvm)


def vcvars_command(vcvars):
    # This is the only shell command. All paths are discovered local tool paths;
    # no project arguments are interpolated into cmd.exe text.
    text = str(vcvars)
    if any(char in text for char in '\r\n"%'):
        raise RuntimeError('Unsupported vcvars path')
    # Pass a raw Windows command line: list2cmdline would backslash-escape
    # embedded quotes, while cmd.exe uses doubled outer quotes instead.
    return f'cmd.exe /d /s /c ""{text}" >nul && set"'


def build_environment(tools):
    result = subprocess.run(vcvars_command(tools['vcvars']), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'vcvars64.bat failed ({result.returncode}): {result.stderr.strip()}')
    output = result.stdout
    # CreateProcess treats variable names case-insensitively. Keeping both
    # PATH and vcvars' Path can discard the LLVM prefix in child PowerShell.
    env = {key.upper(): value for key, value in os.environ.items()}
    env.update((key.upper(), value) for key, value in
               (line.split('=', 1) for line in output.splitlines() if '=' in line and not line.startswith('=')))
    env['PATH'] = str(tools['compiler'].parent) + os.pathsep + env.get('PATH', '')
    return env


def generation_key(root, lock):
    digest = hashlib.sha256(json.dumps(lock, sort_keys=True).encode())
    for path in sorted((root / 'scripts').glob('*.py')) + [root / 'src/gen/spu_workloads.c']:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def generated_ready(root):
    generated = root / 'generated'
    return (all((generated / name).is_file() for name in
                ('ppu_recomp.h', 'ppu_recomp_000.cpp', 'ppu_recomp_001.cpp', 'tj_import_names.h'))
            and len(list((generated / 'spu_images').glob('spujob_*.bin'))) == 18
            and len(list((generated / 'spu_lifted').glob('*/spu_recomp.c'))) == 18)


def generated_digest(root):
    digest = hashlib.sha256()
    generated = root / 'generated'
    for path in sorted(generated.rglob('*')):
        if path.is_file() and path.name != '.lajungla-generation.json':
            digest.update(path.relative_to(generated).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def generate(root, lock, env, skip=False):
    stamp = root / 'generated/.lajungla-generation.json'
    key = generation_key(root, lock)
    try:
        previous = json.loads(stamp.read_text()) if stamp.is_file() else {}
    except (ValueError, OSError):
        previous = {}
    if skip:
        if not generated_ready(root):
            raise RuntimeError('--skip-generation requires complete existing PPU/import/SPU output')
        print('Using existing generated output (--skip-generation)')
        return
    if (previous.get('key') == key and generated_ready(root)
            and previous.get('output') == generated_digest(root)):
        print('Generated output matches content stamp')
        return
    if stamp.exists():
        stamp.unlink()  # failed generation must never retain a valid stamp
    for script, extra in [('analyze.py', []), ('tj_extract_spu_images.py', []),
                          ('tj_lift_spu.py', []), ('fuse_spu_loops.py', ['--apply'])]:
        run([sys.executable, root / 'scripts' / script, *extra], cwd=root, env=env)
    if not generated_ready(root):
        raise RuntimeError('Generation completed without all expected PPU/import/SPU outputs')
    stamp.write_text(json.dumps({'key': key, 'output': generated_digest(root)}, indent=2) + '\n')


def cmake_commands(root, build, runtime, tools, jobs):
    configure = [tools['cmake'], '-S', root, '-B', build, '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=' + str(tools['compiler']),
                 '-DCMAKE_CXX_COMPILER=' + str(tools['compiler']),
                 '-DCMAKE_MAKE_PROGRAM=' + str(tools['ninja']),
                 '-DPS3RECOMP_DIR=' + str(runtime), '-DTJ_ENABLE_SPU=ON']
    return configure, [tools['cmake'], '--build', build, '--parallel', str(min(6, max(1, jobs)))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--runtime-only', action='store_true')
    parser.add_argument('--skip-generation', action='store_true')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build-clang')
    parser.add_argument('-j', '--jobs', type=int, default=6)
    args = parser.parse_args()
    try:
        lock = json.loads((ROOT / 'dependencies.lock.json').read_text())
        if not args.runtime_only:
            validate_elf(ROOT, lock)
        runtime = prepare_runtime(ROOT, lock)
        if args.runtime_only:
            return 0
        tools = discover_tools()
        env = build_environment(tools)
        generate(ROOT, lock, env, args.skip_generation)
        configure, build = cmake_commands(ROOT, args.build_dir.resolve(), runtime, tools, args.jobs)
        run(configure, cwd=ROOT, env=env)
        if not args.configure_only:
            run(build, cwd=ROOT, env=env)
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

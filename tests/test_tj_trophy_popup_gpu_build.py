"""Compile the actual native backend with and without its title callback.
Author: matymeatboy. Does not start the game or mutate a configured build.
"""
from pathlib import Path
import importlib.util
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_native_backend_callback_gate():
    spec = importlib.util.spec_from_file_location('tj_build_support', ROOT/'scripts/build_support.py')
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    tools = support.discover_tools()
    env = support.build_environment(tools)
    runtime = ROOT.parent/'ps3recomp'
    includes = [runtime/'include', runtime/'runtime/spu', ROOT/'src']
    includes += list((runtime/'libs').iterdir())
    common = [str(tools['compiler']), '/nologo', '/std:c17', '/Zs',
              '-Wno-unused-parameter', '-DPS3RECOMP_PROMPT_ART']
    common += ['-I'+str(path) for path in includes if path.is_dir()]
    source = runtime/'libs/video/rsx_d3d12_backend.c'
    for defines in ([], ['-DTJ_TROPHY_POPUP']):
        result = subprocess.run(common + defines + [str(source)], env=env,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == '__main__':
    test_native_backend_callback_gate()
    print('PASS native D3D12 backend compiles with title callback enabled and disabled')

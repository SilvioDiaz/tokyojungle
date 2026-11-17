#!/usr/bin/env python3
"""Adapt disposable split lifter output to Tokyo Jungle's runtime bridge.

Retain the lifter's function bodies and symbol table. Missing entry points are
errors, never generated success-returning stubs.
"""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HELPER_BEGIN = '/* MSVC compatibility helpers */'
HELPER_END = '/* VM base pointer (defined by game project) */'
MARKER = '/* Runtime helpers supplied by recomp_bridge.h */\n\n'
SYMBOL = re.compile(r'\bfunc_[0-9A-Fa-f]{8}\b')
DEFINITION = re.compile(r'^void (func_[0-9A-Fa-f]{8})\(ppu_context\* ctx\)\s*\{', re.M)


def prepare(directory: Path):
    sources = sorted(directory.glob('ppu_recomp_*.cpp'))
    if not sources:
        raise RuntimeError('No split PPU sources; run scripts/analyze.py first')
    texts = {path: path.read_text(encoding='utf-8', errors='surrogateescape')
             for path in sources}
    definitions = set().union(*(set(DEFINITION.findall(text)) for text in texts.values()))
    references = set().union(*(set(SYMBOL.findall(text)) for text in texts.values()))
    missing = sorted(references - definitions)
    if missing:
        raise RuntimeError('Undefined generated entry points: ' + ', '.join(missing))
    patched = {}
    for path, text in texts.items():
        if HELPER_BEGIN in text:
            start = text.index(HELPER_BEGIN)
            end = text.index(HELPER_END, start)
            text = text[:start] + MARKER + text[end:]
        elif MARKER not in text:
            raise RuntimeError('Unrecognized lifter helper preamble: ' + str(path))
        patched[path] = text
    header = ('/* Generated bridge declarations; rerun scripts/analyze.py. */\n'
              '#pragma once\n#include "recomp_bridge.h"\n\n' +
              '\n'.join(f'void {symbol}(ppu_context* ctx);' for symbol in sorted(definitions)) + '\n')
    for path, text in patched.items():
        path.write_text(text, encoding='utf-8', errors='surrogateescape', newline='\n')
    (directory / 'ppu_recomp.h').write_text(header, encoding='utf-8', newline='\n')
    print(f'prepare_ppu_bridge: {len(sources)} sources, {len(definitions)} entry points; no missing stubs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated-dir', type=Path, default=ROOT / 'generated')
    args = parser.parse_args()
    prepare(args.generated_dir)


if __name__ == '__main__':
    main()

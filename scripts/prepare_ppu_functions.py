#!/usr/bin/env python3
"""Recover every 32-byte Tokyo Jungle .lib.stub entry, including the last."""
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]


def import_bounds(data):
    if data[:6] != b'\x7fELF\x02\x02':
        raise ValueError('Expected big-endian ELF64')
    offset = struct.unpack_from('>Q', data, 40)[0]
    stride, count, strings_index = struct.unpack_from('>HHH', data, 58)
    sections = [struct.unpack_from('>IIQQQQ', data, offset + i * stride)
                for i in range(count)]
    strings = sections[strings_index]
    names = data[strings[4]:strings[4] + strings[5]]
    bounds = []
    for name_offset, _, flags, address, file_offset, size in sections:
        name = names[name_offset:].split(b'\0', 1)[0]
        # Retail decrypted ELFs may retain section headers but strip names.
        # Identify those sections by every trampoline's exact instruction form.
        raw = data[file_offset:file_offset + size]
        pattern = (0x39800000, 0x658C0000, 0x818C0000, 0xF8410028,
                   0x800C0000, 0x804C0004, 0x7C0903A6, 0x4E800420)
        masks = (0xFFFFFFFF, 0xFFFF0000, 0xFFFF0000, 0xFFFFFFFF,
                 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        is_stubs = bool(flags & 4 and size and size % 32 == 0 and len(raw) == size)
        if is_stubs:
            is_stubs = all(all(word & mask == expected for word, mask, expected
                               in zip(struct.unpack_from('>8I', raw, at), masks, pattern))
                           for at in range(0, size, 32))
        if name == b'.lib.stub' or is_stubs:
            if not flags & 4 or size % 32:
                raise ValueError('Unexpected .lib.stub geometry')
            bounds.extend((start, start + 32) for start in range(address, address + size, 32))
    if not bounds:
        raise ValueError('Missing executable .lib.stub section')
    return bounds


def main():
    path = ROOT / 'generated/functions_with_opds.json'
    functions = json.loads(path.read_text())
    bounds = import_bounds((ROOT / 'input/EBOOT.ELF').read_bytes())
    lo, hi = bounds[0][0], bounds[-1][1]
    functions = [entry for entry in functions
                 if int(str(entry['end']), 0) <= lo or int(str(entry['start']), 0) >= hi]
    functions.extend({'start': f'0x{start:08X}', 'end': f'0x{end:08X}'}
                     for start, end in bounds)
    functions.sort(key=lambda entry: int(str(entry['start']), 0))
    path.write_text(json.dumps(functions, indent=2) + '\n')
    print(f'prepare_ppu_functions: {len(bounds)} import entry points')


if __name__ == '__main__':
    main()

import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('analyze', ROOT / 'scripts/analyze.py')
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)

def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bridge = load_script('prepare_ppu_bridge')
functions = load_script('prepare_ppu_functions')
post_lift = load_script('post_lift')
imports = load_script('fix_import_slots')


class ExecutableBoundsTests(unittest.TestCase):
    def test_import_stub_section_extends_code_window(self):
        data = bytearray(64 + 3 * 64)
        data[:6] = b'\x7fELF\x02\x02'
        struct.pack_into('>Q', data, 40, 64)
        struct.pack_into('>HH', data, 58, 64, 3)
        for index, flags, addr, size in [(0, 6, 0x10000, 0x24D560),
                                          (1, 6, 0x25D560, 0x27C0),
                                          (2, 2, 0x400000, 0x10000)]:
            struct.pack_into('>IIQQQQ', data, 64 + index * 64,
                             0, 1, flags, addr, 0, size)
        with tempfile.TemporaryDirectory() as directory:
            elf = Path(directory) / 'sample.elf'
            elf.write_bytes(data)
            self.assertEqual(analyze.executable_code_end(elf), 0x25FD20)

    def test_rejects_non_elf(self):
        with tempfile.TemporaryDirectory() as directory:
            elf = Path(directory) / 'sample.elf'
            elf.write_bytes(b'SCE' + bytes(100))
            with self.assertRaises(ValueError):
                analyze.executable_code_end(elf)


class SplitBridgeTests(unittest.TestCase):
    def test_import_slot_validates_thunk_and_sign_extends_displacement(self):
        words = [0x39800000, 0x658C0035, 0x818CFFFC, 0xF8410028,
                 0x800C0000, 0x804C0004, 0x7C0903A6, 0x4E800420]
        read = lambda address: words[(address - 0x25FD00) // 4]
        self.assertEqual(imports.import_slot(read, 0x25FD00), 0x34FFFC)
        words[-1] = 0
        with self.assertRaisesRegex(ValueError, 'Invalid import thunk'):
            imports.import_slot(read, 0x25FD00)

    def test_preserves_table_and_body_and_is_idempotent(self):
        text = ('#include "ppu_recomp.h"\n' + bridge.HELPER_BEGIN +
                '\n#ifdef _MSC_VER\n#ifndef __clang__\nhelper\n#endif\n#endif\n' +
                bridge.HELPER_END + '\nvoid func_00010200(ppu_context* ctx) {\n'
                ' ctx->gpr[3] = 7;\n}\n'
                'const func_entry function_table[] = {{0x10200, func_00010200, "entry"}};\n')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'ppu_recomp_000.cpp'
            source.write_text(text)
            bridge.prepare(directory)
            first = source.read_bytes()
            bridge.prepare(directory)
            self.assertEqual(first, source.read_bytes())
            self.assertIn(b'ctx->gpr[3] = 7;', first)
            self.assertIn(b'const func_entry function_table[]', first)
            self.assertNotIn(b'helper\n', first)
            header = (directory / 'ppu_recomp.h').read_text()
            self.assertIn('#include "recomp_bridge.h"', header)
            self.assertNotIn('typedef', header)

    def test_missing_import_is_error_without_modifying_output(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'ppu_recomp_000.cpp'
            text = 'void func_00010200(ppu_context* ctx) { func_0025FD00(ctx); }\n'
            source.write_text(text)
            with self.assertRaisesRegex(RuntimeError, 'func_0025FD00'):
                bridge.prepare(directory)
            self.assertEqual(source.read_text(), text)
            self.assertFalse((directory / 'missing_stubs.cpp').exists())

    def test_stripped_section_names_recover_final_import(self):
        data = bytearray(64 + 128 + 64)
        data[:6] = b'\x7fELF\x02\x02'
        struct.pack_into('>Q', data, 40, 64)
        struct.pack_into('>HHH', data, 58, 64, 2, 0)
        struct.pack_into('>IIQQQQ', data, 128, 0, 1, 6, 0x25FCE0, 192, 64)
        for at in (192, 224):
            struct.pack_into('>8I', data, at, 0x39800000, 0x658C0034,
                             0x818C2850, 0xF8410028, 0x800C0000, 0x804C0004,
                             0x7C0903A6, 0x4E800420)
        self.assertEqual(functions.import_bounds(data),
                         [(0x25FCE0, 0x25FD00), (0x25FD00, 0x25FD20)])

    def test_font_queue_hooks_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ppu.cpp'
            path.write_text('void func_001C0540(ppu_context* ctx) {\n'
                            '        ctx->gpr[11] = (int64_t)(int32_t)(0x55);\n'
                            '        vm_write32(ctx->gpr[30] + 0x790, ctx->gpr[31]);\n}\n')
            self.assertTrue(post_lift.patch_font_queue_file(path))
            first = path.read_bytes()
            self.assertTrue(post_lift.patch_font_queue_file(path))
            self.assertEqual(first, path.read_bytes())
            self.assertIn(b'tj_font_requests_pending', first)
            self.assertIn(b'ctx->gpr[7] = 20000;', first)


if __name__ == '__main__':
    unittest.main()

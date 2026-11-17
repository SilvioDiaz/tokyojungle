"""Synthetic encrypted SELF fixtures; no game code or user license."""
import struct
import sys
from pathlib import Path

import pytest
from Crypto.Cipher import AES

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from lajungla_self import SelfError, decrypt_self, rap_to_klicensee


def synthetic_self():
    result = bytearray(0x410)
    struct.pack_into('>IIHHIQQ', result, 0, 0x53434500, 2, 0x16, 1, 0x1e0, 0x400, 0x110)
    struct.pack_into('>9Q', result, 0x20, 3, 0x70, 0x90, 0xd0, 0, 0, 0, 0, 0)
    struct.pack_into('>I', result, 0x7c, 4)
    elf = bytearray(64)
    elf[:6] = b'\x7fELF\x02\x02'
    struct.pack_into('>HHIQQQIHHHHHH', elf, 16, 2, 21, 1, 0x10000, 64, 0, 0, 64, 56, 1, 64, 0, 0)
    result[0x90:0xd0] = elf
    struct.pack_into('>II6Q', result, 0xd0, 1, 5, 0x100, 0x10000, 0x10000, 16, 16, 16)
    meta = bytes(range(16))+bytes(16)+bytes(range(16,32))+bytes(16)
    result[0x200:0x240] = AES.new(bytes(32), AES.MODE_CBC, iv=bytes(16)).encrypt(meta)
    md = bytearray(0x1c0)
    struct.pack_into('>II', md, 12, 1, 2)
    struct.pack_into('>QQ8I', md, 32, 0x400, 16, 2, 0, 0, 0, 3, 0, 1, 1)
    md[80:112] = bytes(range(32))
    result[0x240:0x400] = AES.new(meta[:16], AES.MODE_CTR, nonce=b'', initial_value=int.from_bytes(meta[32:48], 'big')).encrypt(md)
    result[0x400:] = AES.new(bytes(range(16)), AES.MODE_CTR, nonce=b'', initial_value=int.from_bytes(bytes(range(16,32)), 'big')).encrypt(b'fixture payload!')
    return bytes(result)


def test_preserves_elf_layout_and_decrypts_segment():
    elf = decrypt_self(synthetic_self(), erk=bytes(32), riv=bytes(16))
    assert len(elf) == 0x110
    assert elf[:6] == b'\x7fELF\x02\x02'
    assert struct.unpack_from('>Q', elf, 32)[0] == 64
    assert elf[0x100:] == b'fixture payload!'


def test_wrong_metadata_key_is_rejected():
    with pytest.raises(SelfError, match='metadatos'):
        decrypt_self(synthetic_self(), erk=bytes([1])*32, riv=bytes(16))


def test_truncated_segment_is_rejected():
    with pytest.raises(SelfError):
        decrypt_self(synthetic_self()[:-1], erk=bytes(32), riv=bytes(16))


@pytest.mark.parametrize('rap', [b'', bytes(15), bytes(17)])
def test_rejects_wrong_rap_size(rap):
    with pytest.raises(SelfError):
        rap_to_klicensee(rap)

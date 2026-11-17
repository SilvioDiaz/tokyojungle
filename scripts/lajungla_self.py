"""Bounded SELF -> ELF reader for LaJungla. Author: matymeatboy.

Adapted format/validation flow from soyjxck/dod3-recomp src/install/self.cpp,
MIT, Copyright 2026 soyjxck and contributors. Includes local-license support.
RAP transformation and public format constants are documented at PS3 Developer
Wiki (Keys / RAP files). User license values are never printed or persisted.
"""
import argparse
import hashlib
import struct
import zlib
from pathlib import Path

from Crypto.Cipher import AES

# Published NPDRM key revision 0x16; not a user's content license.
ERK_16 = bytes.fromhex('7910340483e419e55f0d33e4ea5410eeec3af47814667eca2aa9d75602b14d4b')
RIV_16 = bytes.fromhex('4ad981431b98dfd39b6388edad742a8e')
KLIC_KEY = bytes.fromhex('f2fbca7a75b04edc1390638ccdfdd1ee')
KLIC_FREE = bytes.fromhex('72f990788f9cff745725f08e4c128387')


class SelfError(ValueError):
    pass


def rap_to_klicensee(rap):
    if len(rap) != 16:
        raise SelfError('El RAP debe contener exactamente 16 bytes')
    key = bytearray(AES.new(bytes.fromhex('869f7745c13fd890ccf29188e3cc3edf'), AES.MODE_ECB).decrypt(rap))
    order = [12, 3, 6, 4, 1, 11, 15, 8, 2, 7, 0, 5, 10, 14, 13, 9]
    e1 = bytes.fromhex('a93e1fd67c55a329b75fdda62a95c7a5')
    e2 = bytes.fromhex('67d45da3296d006a4e7c537bf5538c74')
    for _ in range(5):
        for p in order:
            key[p] ^= e1[p]
        for i in range(15, 0, -1):
            key[order[i]] ^= key[order[i-1]]
        carry = 0
        for p in order:
            current = (key[p]-carry) & 255
            if carry != 1 or current != 255:
                carry = int(current < e2[p])
            key[p] = (current-e2[p]) & 255
    return bytes(key)


def decrypt_self(data, klicensee=None, *, erk=ERK_16, riv=RIV_16):
    def read(offset, size):
        if offset < 0 or size < 0 or offset > len(data) or size > len(data)-offset:
            raise SelfError('SELF truncado o intervalo inválido')
        return data[offset:offset+size]

    def unpack(fmt, offset):
        return struct.unpack(fmt, read(offset, struct.calcsize(fmt)))

    def ctr(key, iv, block):
        return AES.new(key, AES.MODE_CTR, nonce=b'', initial_value=int.from_bytes(iv, 'big')).decrypt(block)

    if read(0, 4) != b'SCE\0' or unpack('>H', 10)[0] != 1:
        raise SelfError('No es un SELF de PS3')
    rev = unpack('>H', 8)[0]
    if rev != 0x16:
        raise SelfError(f'Revisión SELF no compatible: {rev:#x}')
    meta_off = 32 + unpack('>I', 12)[0]
    header_size = unpack('>Q', 16)[0]
    app, elf_off, ph_off, sh_off = unpack('>4Q', 0x28)
    ctrl, ctrl_size = unpack('>2Q', 0x58)
    read(0, header_size)
    self_type = unpack('>I', app+12)[0]
    root = read(meta_off, 64)
    if self_type == 8:
        read(ctrl, ctrl_size)
        license_type = None
        end = ctrl+ctrl_size
        while ctrl+16 <= end:
            kind, size = unpack('>II', ctrl)
            if size < 16 or size > end-ctrl:
                raise SelfError('Control SELF inválido')
            if kind == 3 and size >= 96 and read(ctrl+16, 4) == b'NPD\0':
                license_type = unpack('>I', ctrl+24)[0]
                break
            ctrl += size
        if license_type == 3:
            license_key = klicensee if klicensee is not None else KLIC_FREE
        elif license_type in (1, 2):
            if klicensee is None:
                raise SelfError('Este SELF necesita el RAP propio del usuario')
            license_key = klicensee
        else:
            raise SelfError('Tipo de licencia NPDRM no compatible')
        if len(license_key) != 16:
            raise SelfError('Licencia inválida')
        wrapping = AES.new(KLIC_KEY, AES.MODE_ECB).decrypt(license_key)
        root = AES.new(wrapping, AES.MODE_CBC, iv=bytes(16)).decrypt(root)
    elif self_type != 4:
        raise SelfError('SELF no es una aplicación')
    root = AES.new(erk, AES.MODE_CBC, iv=riv).decrypt(root)
    if root[16:32] != bytes(16) or root[48:64] != bytes(16):
        raise SelfError('La licencia o las claves no abren los metadatos')
    if header_size <= meta_off+64:
        raise SelfError('Metadatos SELF ausentes')
    md = ctr(root[:16], root[32:48], read(meta_off+64, header_size-meta_off-64))
    if len(md) < 32:
        raise SelfError('Metadatos SELF truncados')
    nsec, nkeys = struct.unpack_from('>II', md, 12)
    if nsec > 256 or nkeys > 1024 or 32+nsec*48+nkeys*16 > len(md):
        raise SelfError('Tabla de metadatos inválida')
    dkeys = md[32+nsec*48:32+nsec*48+nkeys*16]
    eh = read(elf_off, 64)
    if eh[:6] != b'\x7fELF\x02\x02':
        raise SelfError('ELF no es de 64 bits big-endian')
    e_phoff, e_shoff = struct.unpack_from('>QQ', eh, 32)
    phentsize, phnum, shentsize, shnum = struct.unpack_from('>4H', eh, 54)
    if phentsize != 56 or not 0 < phnum <= 64 or shnum > 4096 or (shnum and shentsize != 64):
        raise SelfError('Cabeceras ELF inválidas')
    ph = read(ph_off, phnum*56)
    segments = [struct.unpack_from('>II6Q', ph, i*56) for i in range(phnum)]
    length = max([64, e_phoff+len(ph), e_shoff+shnum*64] + [p[2]+p[5] for p in segments])
    if length > 256*1024*1024:
        raise SelfError('ELF excede el límite de memoria permitido')
    out = bytearray(length)
    out[:64] = eh
    out[e_phoff:e_phoff+len(ph)] = ph
    if shnum:
        out[e_shoff:e_shoff+shnum*64] = read(sh_off, shnum*64)
    for i in range(nsec):
        off, size, kind, index, _, _, encrypted, ki, vi, compressed = struct.unpack_from('>QQ8I', md, 32+i*48)
        if kind != 2:
            continue
        if index >= phnum:
            raise SelfError('Índice de segmento ELF inválido')
        block = read(off, size)
        if encrypted == 3:
            if ki >= nkeys or vi >= nkeys:
                raise SelfError('Índice de clave de segmento inválido')
            block = ctr(dkeys[ki*16:ki*16+16], dkeys[vi*16:vi*16+16], block)
        elif encrypted not in (0, 1):
            raise SelfError('Cifrado de segmento no compatible')
        dest, expected = segments[index][2], segments[index][5]
        if compressed == 2:
            try:
                decoder = zlib.decompressobj()
                block = decoder.decompress(block, expected+1)
                if not decoder.eof or decoder.unconsumed_tail:
                    raise SelfError('Segmento comprimido inválido')
            except zlib.error as exc:
                raise SelfError('El segmento no se descomprime') from exc
        if len(block) != expected:
            raise SelfError('Tamaño de segmento ELF incorrecto')
        out[dest:dest+expected] = block
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description='Prepara el ELF de tu copia para LaJungla')
    parser.add_argument('self', type=Path)
    parser.add_argument('--rap', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    key = rap_to_klicensee(args.rap.read_bytes()) if args.rap else None
    elf = decrypt_self(args.self.read_bytes(), key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(elf)
    print(f'ELF: {len(elf)} bytes, SHA-256 {hashlib.sha256(elf).hexdigest()}')


if __name__ == '__main__':
    main()

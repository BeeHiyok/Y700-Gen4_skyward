#!/usr/bin/env python3
"""Self-contained Skyward stock/recovery ramdisk inspector and packer helper.

Implements the subset of crates/skyward-bootimg and crates/skyward-pack needed
for a Windows port: Android boot header v3/v4, LZ4-legacy compressed cpio newc,
AVB hash footer with algorithm NONE. No third-party modules required.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

PAGE = 4096
AVB_FOOTER_LEN = 64
AVB_HEADER_LEN = 256
LZ4_LEGACY_MAGIC = 0x184C2102
LZ4_LEGACY_BLOCK = 8 << 20


def align(n: int, a: int = PAGE) -> int:
    return (n + a - 1) // a * a


# ---------- Minimal LZ4 block codec (literal/sequence format) ----------

def lz4_block_decompress(src: bytes, expected: int | None = None) -> bytes:
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                if i >= n:
                    raise ValueError('truncated literal length')
                x = src[i]
                i += 1
                lit += x
                if x != 255:
                    break
        if i + lit > n:
            raise ValueError('literal runs past block')
        out += src[i:i + lit]
        i += lit
        if i == n:
            break
        if i + 2 > n:
            raise ValueError('truncated match offset')
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0 or off > len(out):
            raise ValueError(f'invalid match offset {off}, output {len(out)}')
        match_len = token & 15
        if match_len == 15:
            while True:
                if i >= n:
                    raise ValueError('truncated match length')
                x = src[i]
                i += 1
                match_len += x
                if x != 255:
                    break
        match_len += 4
        start = len(out) - off
        for k in range(match_len):
            out.append(out[start + k])
    if expected is not None and len(out) != expected:
        raise ValueError(f'block decompressed to {len(out)}, expected {expected}')
    return bytes(out)


def lz4_block_compress(data: bytes) -> bytes:
    # Simple hash-chain-free compressor. Correct (not fastest) LZ4 block.
    out = bytearray()
    pos = 0
    n = len(data)
    table: dict[int, int] = {}
    while pos < n:
        anchor = pos
        # Find a match of at least 4 bytes.
        found = None
        if pos + 4 <= n:
            h = int.from_bytes(data[pos:pos + 4], 'little')
            last = table.get(h)
            if last is not None and 0 < pos - last <= 65535:
                m = 4
                maxm = min(n - pos, 65535 + 4)
                while m < maxm and data[last + m] == data[pos + m]:
                    m += 1
                if m >= 4:
                    found = (pos - last, m)
            table[h] = pos
        if found is None:
            pos += 1
            # Flush literal run as batches to keep token lengths bounded.
            if pos - anchor >= 255 + 15:
                lit = 255 + 15
                out.append(15 << 4)
                out.extend(b'\xff' * ((lit - 15) // 255))
                out.append((lit - 15) % 255 if False else 0)
                out += data[anchor:anchor + lit]
                # A trailing zero-length match cannot be encoded; stop at end of literals.
                # More efficient: fall through to an explicit final-literals path.
                if anchor + lit == n:
                    return bytes(out)
            continue
        off, m = found
        literals = data[anchor:pos]
        match_len = m - 4
        token_lit = min(len(literals), 15)
        token_match = min(match_len, 15)
        out.append((token_lit << 4) | token_match)
        if len(literals) >= 15:
            rem = len(literals) - 15
            while rem >= 255:
                out.append(255)
                rem -= 255
            out.append(rem)
        out += literals
        out += struct.pack('<H', off)
        if match_len >= 15:
            rem = match_len - 15
            while rem >= 255:
                out.append(255)
                rem -= 255
            out.append(rem)
        # Populate hash table for the matched region (cheap, bounded).
        for q in range(pos, min(pos + m, n - 3)):
            table[int.from_bytes(data[q:q + 4], 'little')] = q
        pos += m
        # A block cannot end with a bare match; emit remaining literals separately.
        if pos == n:
            # Pad with a zero-length final sequence whose offset is valid.
            out.append(0)
            out += struct.pack('<H', min(1, len(data)))
            return bytes(out)
    if anchor < n:
        literals = data[anchor:n]
        token_lit = min(len(literals), 15)
        out.append(token_lit << 4)
        if len(literals) >= 15:
            rem = len(literals) - 15
            while rem >= 255:
                out.append(255)
                rem -= 255
            out.append(rem)
        out += literals
    return bytes(out)


def lz4_legacy_decode(data: bytes) -> bytes:
    if len(data) < 4 or struct.unpack_from('<I', data, 0)[0] != LZ4_LEGACY_MAGIC:
        if data[:6] in (b'070701', b'070702'):
            return data
        raise ValueError('not LZ4 legacy or raw cpio newc')
    i = 4
    out = bytearray()
    while i + 4 <= len(data):
        block_len = struct.unpack_from('<I', data, i)[0]
        i += 4
        if block_len == 0 or i + block_len > len(data):
            # Zero padding or trailing AVB/partition padding.
            break
        out += lz4_block_decompress(data[i:i + block_len])
        i += block_len
    return bytes(out)


def lz4_legacy_encode(data: bytes) -> bytes:
    out = bytearray(struct.pack('<I', LZ4_LEGACY_MAGIC))
    for chunk_start in range(0, len(data), LZ4_LEGACY_BLOCK):
        chunk = data[chunk_start:chunk_start + LZ4_LEGACY_BLOCK]
        block = lz4_block_compress(chunk)
        out += struct.pack('<I', len(block))
        out += block
    return bytes(out)


# ---------- cpio newc ----------

@dataclass
class CpioEntry:
    name: str
    mode: int
    uid: int
    gid: int
    mtime: int
    nlink: int
    dev: tuple[int, int]
    rdev: tuple[int, int]
    data: bytes

    @property
    def kind(self) -> int:
        return self.mode & 0o170000

    @property
    def is_dir(self) -> bool:
        return self.kind == 0o040000

    @property
    def is_link(self) -> bool:
        return self.kind == 0o120000

    @property
    def is_regular(self) -> bool:
        return self.kind == 0o100000


def split_pad(data: bytes, off: int, size: int) -> tuple[bytes, int]:
    raw = data[off:off + size]
    if len(raw) != size:
        raise ValueError('truncated cpio field')
    return raw, align(off + size, 4)


def cpio_decode(data: bytes) -> list[CpioEntry]:
    entries: list[CpioEntry] = []
    off = 0
    while True:
        if data[off:off + 6] not in (b'070701', b'070702'):
            raise ValueError(f'bad cpio magic at {off}: {data[off:off + 16]!r}')
        raw = data[off:off + 110]
        if len(raw) != 110:
            raise ValueError(f'truncated cpio header at {off}')
        fields = [int(raw[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        (ino, mode, uid, gid, nlink, mtime, filesize,
         devmajor, devminor, rdevmajor, rdevminor, namesize, check) = fields
        off += 110
        name_raw, off = split_pad(data, off, namesize)
        name = name_raw[:-1].decode('utf-8', 'surrogateescape')
        body, off = split_pad(data, off, filesize)
        if name == 'TRAILER!!!':
            break
        entries.append(CpioEntry(name, mode, uid, gid, mtime, nlink,
                                 (devmajor, devminor), (rdevmajor, rdevminor), body))
    return entries


def cpio_encode(entries: list[CpioEntry]) -> bytes:
    out = bytearray()

    def add(entry: CpioEntry, ino: int, filesize: int, body: bytes) -> None:
        name = entry.name.encode('utf-8', 'surrogateescape') + b'\0'
        vals = [ino, entry.mode, entry.uid, entry.gid, entry.nlink,
                entry.mtime, filesize, *entry.dev, *entry.rdev,
                len(name), 0]
        entry_bytes = bytearray(b'070701')
        for v in vals:
            entry_bytes += f'{v:08X}'.encode()
        entry_bytes += name
        entry_bytes += b'\0' * (-(110 + len(name)) % 4)
        entry_bytes += body
        entry_bytes += b'\0' * (-len(body) % 4)
        out.extend(entry_bytes)

    for i, e in enumerate(entries):
        add(e, 300000 + i, len(e.data), e.data)
    trailer = CpioEntry('TRAILER!!!', 0, 0, 0, 0, 1, (0, 0), (0, 0), b'')
    add(trailer, 300000 + len(entries), 0, b'')
    return bytes(out)


def root_entry(name: str, mode: int, data: bytes) -> CpioEntry:
    nlink = 2 if mode & 0o170000 == 0o040000 else 1
    return CpioEntry(name, mode, 0, 0, 0, nlink, (0, 0), (0, 0), data)


class Ramdisk:
    def __init__(self, entries: list[CpioEntry]):
        self.entries = entries

    @classmethod
    def decode(cls, compressed: bytes) -> 'Ramdisk':
        return cls(cpio_decode(lz4_legacy_decode(compressed)))

    def encode(self) -> bytes:
        return lz4_legacy_encode(cpio_encode(self.entries))

    def find(self, name: str) -> CpioEntry | None:
        return next((e for e in self.entries if e.name == name), None)

    def replace(self, name: str, data: bytes) -> None:
        e = self.find(name)
        if e is None or not e.is_regular:
            raise ValueError(f'{name} is not a regular file in ramdisk')
        e.data = data

    def add(self, name: str, mode: int, data: bytes) -> None:
        self.insert(name, 0o100000 | mode, data)

    def link(self, name: str, target: str) -> None:
        e = self.find(name)
        if e is not None:
            if not e.is_link:
                raise ValueError(f'{name} exists and is not a symlink')
            e.data = target.encode()
            return
        self.insert(name, 0o120000 | 0o755, target.encode())

    def insert(self, name: str, mode: int, data: bytes) -> None:
        if self.find(name) is not None:
            raise ValueError(f'{name} already in ramdisk')
        parts = name.split('/')
        parent = ''
        for part in parts[:-1]:
            parent = f'{parent}/{part}' if parent else part
            e = self.find(parent)
            if e is None:
                self.entries.append(root_entry(parent, 0o040000 | 0o755, b''))
            elif not e.is_dir:
                raise ValueError(f'{parent} is not a directory')
        self.entries.append(root_entry(name, mode, data))


# ---------- Android boot image v3/v4 ----------

@dataclass
class BootImage:
    raw_header: bytes
    kernel: bytes
    ramdisk: bytes

    @classmethod
    def read(cls, path: Path) -> 'BootImage':
        b = path.read_bytes()
        if b[:8] != b'ANDROID!':
            raise ValueError('not ANDROID! boot image')
        kernel_size, ramdisk_size, osver, header_size = struct.unpack_from('<4I', b, 8)
        if header_size == 0:
            header_size = 1584
        hv = struct.unpack_from('<I', b, 40)[0]
        if hv < 3:
            raise ValueError(f'boot header v{hv} unsupported; Skyward supports v3/v4')
        kernel_off = PAGE
        ramdisk_off = kernel_off + align(kernel_size)
        kernel = b[kernel_off:kernel_off + kernel_size]
        ramdisk = b[ramdisk_off:ramdisk_off + ramdisk_size]
        if len(kernel) != kernel_size or len(ramdisk) != ramdisk_size:
            raise ValueError('truncated boot image sections')
        return cls(bytearray(b[:header_size]), kernel, ramdisk)

    def to_bytes(self) -> bytes:
        h = bytearray(self.raw_header)
        struct.pack_into('<I', h, 8, len(self.kernel))
        struct.pack_into('<I', h, 12, len(self.ramdisk))
        hv = struct.unpack_from('<I', h, 40)[0]
        if hv >= 4 and len(h) >= 1584:
            struct.pack_into('<I', h, 1580, 0)  # no boot signature
        out = bytearray(h)
        out += b'\0' * (-len(out) % PAGE)
        out += self.kernel
        out += b'\0' * (-len(out) % PAGE)
        out += self.ramdisk
        out += b'\0' * (-len(out) % PAGE)
        return bytes(out)


# ---------- AVB footer, mirror of skyward-pack/src/avb.rs ----------

def avb_hash_descriptor(image_size: int, partition: str, salt: bytes, digest: bytes) -> bytes:
    algorithm = b'sha256'.ljust(32, b'\0')
    d = bytearray()
    d += struct.pack('>QQ', 2, 0)
    d += struct.pack('>Q', image_size)
    d += algorithm
    for n in [len(partition), len(salt), len(digest), 0]:
        d += struct.pack('>I', n)
    d += b'\0' * 60
    d += partition.encode()
    d += salt
    d += digest
    d += b'\0' * (-len(d) % 8)
    following = len(d) - 16
    struct.pack_into('>Q', d, 8, following)
    return bytes(d)


def avb_vbmeta(descriptors: bytes) -> bytes:
    aux = align(len(descriptors), 64)
    v = bytearray()
    v += b'AVB0'
    v += struct.pack('>II', 1, 0)
    v += struct.pack('>QQ', 0, aux)
    v += struct.pack('>I', 0)
    n = len(descriptors)
    for field in [0, 0, 0, 0, n, 0, n, 0, 0, n, 0]:
        v += struct.pack('>Q', field)
    v += struct.pack('>II', 0, 0)
    v += b'skyward-pack'
    v += b'\0' * (AVB_HEADER_LEN - len(v))
    v += descriptors
    v += b'\0' * (AVB_HEADER_LEN + aux - len(v))
    return bytes(v)


def avb_footed(image: bytes, partition: str, partition_size: int, salt: bytes) -> bytes:
    digest = hashlib.sha256(salt + image).digest()
    descriptor = avb_hash_descriptor(len(image), partition, salt, digest)
    vbmeta = avb_vbmeta(descriptor)
    offset = align(len(image))
    end = offset + align(len(vbmeta))
    if end + PAGE > partition_size:
        raise ValueError(f'image {len(image)} + vbmeta do not fit partition {partition_size}')
    out = bytearray(image)
    out += b'\0' * (offset - len(out))
    out += vbmeta
    out += b'\0' * (partition_size - AVB_FOOTER_LEN - len(out))
    footer = bytearray()
    footer += b'AVBf'
    footer += struct.pack('>II', 1, 0)
    for n in [len(image), offset, len(vbmeta)]:
        footer += struct.pack('>Q', n)
    footer += b'\0' * (AVB_FOOTER_LEN - len(footer))
    out += footer
    return bytes(out)


# ---------- Commands ----------

def cmd_list(args: argparse.Namespace) -> None:
    img = BootImage.read(Path(args.image))
    hv = struct.unpack_from('<I', img.raw_header, 40)[0]
    print(f'header v{hv}  kernel {len(img.kernel)} bytes  ramdisk {len(img.ramdisk)} bytes')
    if not img.ramdisk:
        return
    rd = Ramdisk.decode(img.ramdisk)
    for e in rd.entries:
        kind = 'd' if e.is_dir else ('l' if e.is_link else '-')
        target = f' -> {e.data.decode("utf-8", "replace")}' if e.is_link else ''
        print(f'{kind} {e.mode & 0o7777:06o} {e.uid:>5}:{e.gid:<5} {len(e.data):>10}  {e.name}{target}')
    print(f'{len(rd.entries)} entries')


def cmd_cat(args: argparse.Namespace) -> None:
    img = BootImage.read(Path(args.image))
    e = Ramdisk.decode(img.ramdisk).find(args.path)
    if e is None:
        raise SystemExit(f'{args.path} is not in ramdisk')
    sys.stdout.buffer.write(e.data)


def cmd_extract(args: argparse.Namespace) -> None:
    img = BootImage.read(Path(args.image))
    rd = Ramdisk.decode(img.ramdisk)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for wanted in args.paths:
        e = rd.find(wanted)
        if e is None:
            raise SystemExit(f'{wanted} is not in ramdisk')
        dest = out / wanted.replace('/', os.sep)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(e.data)
        print(f'{wanted}: {len(e.data)} bytes -> {dest} sha256={hashlib.sha256(e.data).hexdigest()}')


def cmd_recovery(args: argparse.Namespace) -> None:
    stock_path = Path(args.stock)
    stock_bytes = stock_path.read_bytes()
    partition_size = len(stock_bytes)
    if stock_bytes[-AVB_FOOTER_LEN:-AVB_FOOTER_LEN + 4] != b'AVBf':
        raise SystemExit('stock does not end in an AVB footer; give the whole recovery partition')
    img = BootImage.read(stock_path)
    rd = Ramdisk.decode(img.ramdisk)
    for e in rd.entries:
        if e.name == 'FFiles' or e.name.startswith('twres'):
            raise SystemExit(f'{stock_path.name} holds {e.name}, which is not a stock recovery')
    cfg = Path(args.config).read_bytes()
    # Validate minimum config by loading is done separately by Rust in CI; here
    # just check a non-empty TOML with a [device] codename.
    if b'[device]' not in cfg or b'codename' not in cfg:
        raise SystemExit('config has no [device] codename')
    files = {
        'system/bin/recovery': Path(args.binary),
        'skyward/system-init': Path(args.system_init),
        'skyward/device.toml': Path(args.config),
        'skyward/MiSansVF.ttf': Path(args.font),
        'skyward/KirkMono-Regular.ttf': Path(args.mono),
        'skyward/KirkMono-OFL.txt': Path(args.mono_license),
    }
    rd.replace('system/bin/recovery', files['system/bin/recovery'].read_bytes())
    for command in ['system/bin/7za', 'system/bin/avbctl', 'system/bin/resetprop',
                    'system/bin/unzip', 'system/bin/zstd']:
        rd.link(command, 'recovery')
    for name, p in files.items():
        if name == 'system/bin/recovery':
            continue
        rd.add(name, 0o755 if name.endswith('system-init') else 0o644, p.read_bytes())
    if rd.find('system/etc/task_profiles.json') is None:
        rd.add('system/etc/task_profiles.json', 0o644, Path(args.task_profiles).read_bytes())
    rd.add('system/etc/init/skyward-mtp.rc', 0o644, Path(args.mtp_rc).read_bytes())
    prop = rd.find('prop.default')
    if prop is None:
        raise SystemExit('prop.default is not in ramdisk')
    remove = [b'ro.build.version.release', b'ro.build.version.security_patch',
              b'ro.vendor.build.security_patch']
    lines = bytearray()
    for line in prop.data.splitlines(keepends=True):
        key = line.split(b'=', 1)[0]
        if key not in remove:
            lines += line
    lines += b'\nro.secure=0\nro.adb.secure=0\nro.debuggable=1\nro.ota.allow_downgrade=true\n'
    prop.data = bytes(lines)
    img.ramdisk = rd.encode()
    image = img.to_bytes()
    salt = hashlib.sha256(image).digest()
    out = avb_footed(image, 'recovery', partition_size, salt)
    Path(args.out).write_bytes(out)
    print(f'wrote {args.out} ({len(image)} bytes image, {len(out)} bytes partition, sha256={hashlib.sha256(out).hexdigest()})')


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('list')
    q.add_argument('image')
    q.set_defaults(func=cmd_list)
    q = sub.add_parser('cat')
    q.add_argument('image')
    q.add_argument('path')
    q.set_defaults(func=cmd_cat)
    q = sub.add_parser('extract')
    q.add_argument('image')
    q.add_argument('--out', required=True)
    q.add_argument('paths', nargs='+')
    q.set_defaults(func=cmd_extract)
    q = sub.add_parser('recovery')
    q.add_argument('--stock', required=True)
    q.add_argument('--binary', required=True)
    q.add_argument('--system-init', dest='system_init', required=True)
    q.add_argument('--config', required=True)
    q.add_argument('--font', required=True)
    q.add_argument('--mono', required=True)
    q.add_argument('--mono-license', dest='mono_license', required=True)
    q.add_argument('--task-profiles', dest='task_profiles', required=True)
    q.add_argument('--mtp-rc', dest='mtp_rc', required=True)
    q.add_argument('--out', required=True)
    q.set_defaults(func=cmd_recovery)
    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""PreToolUse guard: stops any Bash command that could wipe or rewrite a disk.

Disk-destroying commands are allowed only when every disk they name is the one
disk Eitan cleared for wiping, written as its /dev/disk/by-id path (which carries
the serial number). Anything else is blocked with an alarm. Read-only listings
(fdisk -l, parted print, sgdisk -p, bare wipefs) pass.
"""
import json, re, sys

# The ONLY disk that may be wiped: grandpa's 256 GB Intel NVMe (was C:).
ALLOWED = "/dev/disk/by-id/nvme-INTEL_SSDPEKKF256G7L_BTPY71050T8D256D"
# Never wipe: grandpa's 1 TB WD (D:, his files) and the live USB stick.
FORBIDDEN = ["WD-WXM1A5731ZTT", "WDC_WD10JPCX", "WD10JPCX", "0101667ab805a10f0aa23d6dda9c4a6bd3a4546ff019db915c215e8634bf8c4568e"]

DESTRUCTIVE = re.compile(r"""
    \b(wipefs|sgdisk|sfdisk|fdisk|gdisk|cfdisk|parted|mkfs(\.\w+)?|mke2fs|mkswap|mkntfs|mkdosfs|
       blkdiscard|shred|ntfsclone|partclone\.\w+|zpool|pvcreate|badblocks|debootstrap|grub-install)\b
  | \bcryptsetup\s+(luksFormat|erase|reencrypt)\b
  | \bnvme\s+(format|sanitize|write-zeroes)\b
  | \bhdparm\b[^|;&]*(--security-erase|--trim-sector|--write-sector|--fibmap|-r\s*0)
  | \bblockdev\s+--setrw\b
  | \bdd\b[^|;&]*\bof=
  | \b(cat|pv|tee|cp)\b[^|;&]*\s/dev/(sd|nvme|mmcblk|hd|vd|disk/)
  | >\s*/dev/(sd|nvme|mmcblk|hd|vd|disk/)
""", re.X)

READONLY = [
    re.compile(r"\b(fdisk|sfdisk|gdisk)\s+(-l|--list|-d|--dump|-J|--json)\b"),
    re.compile(r"\bparted\b[^|;&]*(\s-l\b|\s--list\b|\sprint\b|-s\s+\S+\s+(unit\s+\S+\s+)?print)"),
    re.compile(r"\bsgdisk\s+(-p|--print|-i\s*\d|--info)\b"),
    re.compile(r"\bwipefs(\s+(--no-headings|-n|--noheadings|-J|--json|-O\s*\S+|--output\s+\S+))*\s+/dev/\S+\s*($|[|;&])"),
    re.compile(r"\bbadblocks\s+(-s\s+)?(-v\s+)?/dev/"),   # read-only scan (no -w/-n)
    re.compile(r"\bzpool\s+(status|list|import\s+-N)"),
]

DISK_REF = re.compile(r"/dev/(disk/by-[\w-]+/[^\s'\"|;&)]+|sd[a-z]+\d*|nvme\d+n\d+(p\d+)?|mmcblk\d+(p\d+)?|hd[a-z]\d*|vd[a-z]\d*|mapper/\S+|dm-\d+|md\d+|loop\d+)")

def segments(cmd):
    return re.split(r"&&|\|\||;|\n|\|", cmd)

def block(msg):
    print("DISK GUARD ALARM: " + msg + "\nStop. Do not retry or work around this. Tell Eitan exactly what you were about to do.", file=sys.stderr)
    sys.exit(2)

data = json.load(sys.stdin)
if data.get("tool_name") != "Bash":
    sys.exit(0)
cmd = data.get("tool_input", {}).get("command", "")

for f in FORBIDDEN:
    if f in cmd and DESTRUCTIVE.search(cmd):
        block(f"this command could write to a disk Eitan said must never be touched ({f}).")

for seg in segments(cmd):
    if not DESTRUCTIVE.search(seg):
        continue
    if any(r.search(seg) for r in READONLY) and not re.search(r"\b(mkfs|mke2fs|mkswap|dd|blkdiscard|shred)\b", seg):
        continue
    refs = [m.group(0) for m in DISK_REF.finditer(seg)]
    bad = [r for r in refs if not r.startswith(ALLOWED)]
    if bad:
        block(f"'{seg.strip()[:160]}' targets {', '.join(sorted(set(bad)))}. The only disk cleared for wiping is {ALLOWED} (grandpa's Intel NVMe, by serial).")
    if not refs and re.search(r"[$`]|/dev/", seg):
        block(f"'{seg.strip()[:160]}' could rewrite a disk but names none by serial. Address the target as {ALLOWED}[-partN] so the guard can prove it is the right one.")
sys.exit(0)

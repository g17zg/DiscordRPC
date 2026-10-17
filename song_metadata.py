import os
import sys
import shutil
import subprocess
import time
import re
import os
from pypresence.types import ActivityType

print("made with 💖 by g17zg")

def get_resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)



bat_path = get_resource_path("daemon.bat")


wnpclipath = r"C:\Program Files\wnpcli 3.0.0-alpha.6\bin"

# Use the Application's Client ID from https://discord.com/developers/applications
DISCORD_CLIENT_ID = input("enter application id: \n")  # e.g. "123456789012345678"
DISABLE_RPC = False
RPC_DEBUG = False


def find_wnpcli():
    candidates = [
        os.path.join(wnpclipath, "wnpcli.exe"),
        os.path.join(wnpclipath, "wnpcli"),
        "wnpcli",
    ]

    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # Try to find on PATH
    which = shutil.which("wnpcli")
    if which:
        return which

    raise FileNotFoundError("wnpcli executable not found. Check wnpclipath or install WebNowPlaying-CLI.")


def get_raw_metadata():
    exe = find_wnpcli()
    try:
        proc = subprocess.run([exe, "metadata"], capture_output=True)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return decode_bytes(proc.stdout)


def decode_bytes(b: bytes) -> str:
    if b is None:
        return ""
    if isinstance(b, str):
        return b

    #utf16
    try:
        if len(b) >= 4:
            odd_bytes = b[1::2]
            unique_odds = set(odd_bytes)
            # odd bytes non zero
            if len(unique_odds) == 1 and next(iter(unique_odds)) != 0x00:
                # ensure even bytes are mostly printable ASCII/latin-1
                even_bytes = b[0::2]
                printable = sum(1 for x in even_bytes if 32 <= x <= 126)
                if printable >= max(3, len(even_bytes) // 3):
                    # decode as UTF-16LE code
                    def pairwise_decode_bytes(byte_seq, byteorder='little'):
                        chars = []
                        for i in range(0, len(byte_seq) - 1, 2):
                            code = int.from_bytes(byte_seq[i:i+2], byteorder=byteorder)
                            try:
                                chars.append(chr(code))
                            except Exception:
                                continue
                        return ''.join(chars).replace('\x00', '')

                    cand = pairwise_decode_bytes(b, 'little')
                    if cand:
                        return cand
    except Exception:
        pass

    # try encodings
    tried = []
    encodings = ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1252']
    for enc in encodings:
        try:
            s = b.decode(enc)
            # remove embedded NULs
            if '\x00' in s:
                s = s.replace('\x00', '')
            tried.append((enc, s))
        except Exception:
            continue

    candidates = []
    for enc in ('utf-16-le', 'utf-16-be'):
        try:
            s = b.decode(enc)
            if '\x00' in s:
                s = s.replace('\x00', '')
            candidates.append((enc, s))
        except Exception:
            continue

    def score_string(s: str) -> int:
        if not s:
            return -1000
        ctrl = sum(1 for ch in s if ord(ch) < 32 and ch not in '\r\n\t')
        letters = sum(1 for ch in s if ch.isalpha())
        cyrillic = sum(1 for ch in s if 0x0400 <= ord(ch) <= 0x04FF)
        # penalize CJK / rare-symbol
        cjk = sum(1 for ch in s if 0x2E80 <= ord(ch) <= 0x9FFF)
        return letters + (cyrillic * 5) - (cjk * 10) - (ctrl * 5)

    best = None
    best_score = -10**9
    for enc, s in tried + candidates:
        sc = score_string(s)
        if sc > best_score:
            best_score = sc
            best = s

    if best is None:
        try:
            return b.decode('latin-1').replace('\x00', '')
        except Exception:
            return ''
    # decode and pairwise
    noisy_ctrl = sum(1 for ch in best if ord(ch) < 32 and ch not in '\r\n\t')
    if noisy_ctrl > 0:
        candidates2 = [(best_score, best)]
        # try proper utf-16-le/be decodes
        for enc in ('utf-16-le', 'utf-16-be'):
            try:
                s = b.decode(enc)
                if '\x00' in s:
                    s = s.replace('\x00', '')
                candidates2.append((score_string(s), s))
            except Exception:
                # try a pairwise reconstruction as a last resort
                try:
                    chars = []
                    for i in range(0, len(b) - 1, 2):
                        code = int.from_bytes(b[i:i+2], byteorder='little' if enc.endswith('le') else 'big')
                        try:
                            chars.append(chr(code))
                        except Exception:
                            continue
                    s = ''.join(chars).replace('\x00', '')
                    candidates2.append((score_string(s), s))
                except Exception:
                    pass

        # choose best-scoring candidate
        candidates2.sort(key=lambda x: x[0], reverse=True)
        chosen = candidates2[0][1]
        return chosen

    return best


def get_fields_quick():
    exe = find_wnpcli()
    fmt = "{artist}\t{title}\t{position}\t{duration}"
    try:
        proc = subprocess.run([exe, "-f", fmt, "metadata"], capture_output=True)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    out = decode_bytes(proc.stdout).strip()
    # fix possible interleaved UTF-16 mojibake in quick fields
    parts = [fix_interleaved_utf16(p).strip() for p in out.split("\t")]
    # if wnpcli left placeholders unsubstituted it will contain '{'
    if "{" in out:
        return None
    if len(parts) < 4:
        return None
    return tuple(p for p in parts[:4])


def parse_raw_metadata(raw):
    data = {}
    if not raw:
        return data

    for line in raw.splitlines():
        if not line or not line.strip():
            continue
        # Prefer splitting where there are multiple spaces (column separator)
        m = re.split(r"\s{2,}", line, maxsplit=1)
        if len(m) >= 2:
            key = m[0].strip()
            val = m[1].strip()
        else:
            parts = line.split(None, 1)
            if len(parts) == 1:
                key = parts[0].strip()
                val = ""
            else:
                key, val = parts[0].strip(), parts[1].strip()

        if key:
            # Attempt to fix common mojibake where UTF-16LE bytes were
            # mis-decoded into a str with interleaved control chars (e.g. '\x04').
            val = fix_interleaved_utf16(val)
            data[key] = val
            data[key.replace('-', '_')] = val

    return data


def find_field(raw, keys):
    if not raw:
        return ""
    for key in keys:
        m = re.search(rf"^\s*{re.escape(key)}\s+(.*)$", raw, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""


def sec_to_mmss(s):
    try:
        s = int(s)
    except Exception:
        return str(s)
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def fix_interleaved_utf16(s: str) -> str:
    if not s:
        return s
    ctrl_count = sum(1 for ch in s if ord(ch) < 32 and ch not in '\r\n\t')
    # fast path: if there are no control chars, assume string is fine
    if ctrl_count == 0:
        return s

    try:
        raw = s.encode('latin-1', errors='ignore')
    except Exception:
        return s

    def try_decode(raw_bytes, byteorder):
        chars = []
        for i in range(0, len(raw_bytes) - 1, 2):
            code = int.from_bytes(raw_bytes[i:i+2], byteorder=byteorder)
            try:
                chars.append(chr(code))
            except Exception:
                continue
        return ''.join(chars).replace('\x00', '')

    cand_le = try_decode(raw, 'little')
    cand_be = try_decode(raw, 'big')

    # Score candidates: prefer one with more letters and fewer control chars
    def score(x: str) -> int:
        if not x:
            return -1000
        ctrl = sum(1 for ch in x if ord(ch) < 32 and ch not in '\r\n\t')
        letters = sum(1 for ch in x if ch.isalpha())
        cyrillic = sum(1 for ch in x if 0x0400 <= ord(ch) <= 0x04FF)
        cjk = sum(1 for ch in x if 0x2E80 <= ord(ch) <= 0x9FFF)
        return letters + (cyrillic * 5) - (cjk * 10) - (ctrl * 5)

    candidates = [(score(s), s), (score(cand_le), cand_le), (score(cand_be), cand_be)]
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    return best


def format_status(raw):
    # parse raw
    data = parse_raw_metadata(raw)

    def get_first(keys):
        for k in keys:
            if k in data and data[k].strip():
                return data[k].strip()
            # try underscore variant
            uk = k.replace('-', '_')
            if uk in data and data[uk].strip():
                return data[uk].strip()
        return ""

    artist = get_first(["artist", "album-artist", "album_artist", "name"]) or ""
    title = get_first(["title", "name"]) or ""

    pos = get_first(["position", "position-sec", "position_sec"]) or ""
    if pos.isdigit():
        pos = sec_to_mmss(pos)

    dur = get_first(["duration", "duration-sec", "duration_sec"]) or ""
    if dur.isdigit():
        dur = sec_to_mmss(dur)

    name_part = " - ".join(x for x in (artist.strip(), title.strip()) if x)
    time_part = ""
    if pos and dur:
        time_part = f"{pos} / {dur}"
    elif pos:
        time_part = pos
    elif dur:
        time_part = f"0:00 / {dur}" if dur else ""

    parts = []
    if name_part:
        parts.append(name_part)
    if time_part:
        parts.append(time_part)

    return " | ".join(parts) if parts else "No song playing"


def main():
    once = len(sys.argv) > 1 and sys.argv[1].lower() == "once"
    prev_len = 0
    try:
        discord_client_id = DISCORD_CLIENT_ID
        rpc = None
        if discord_client_id and not DISABLE_RPC:
            try:
                if RPC_DEBUG:
                    print(f"[RPC] attempting to import pypresence and connect (client_id={discord_client_id})", file=sys.stderr)
                from pypresence import Presence

                rpc = Presence(discord_client_id)
                rpc.connect()
                if RPC_DEBUG:
                    print("[RPC] connected", file=sys.stderr)
            except Exception as e:
                print(f"Discord RPC init failed: {e}", file=sys.stderr)
                rpc = None

        while True:
            quick = get_fields_quick()
            raw = get_raw_metadata()
            parsed = parse_raw_metadata(raw)
            if once:
                print("--- raw metadata (debug) ---", file=sys.stderr)
                print(raw or "<no output>", file=sys.stderr)
                parsed = parse_raw_metadata(raw)
                print("--- parsed keys (debug) ---", file=sys.stderr)
                for k in sorted(parsed.keys()):
                    print(f"{k}: {parsed[k]}", file=sys.stderr)
                print("--- end debug ---", file=sys.stderr)
            if quick:
                artist_q, title_q, pos_q, dur_q = quick
                if pos_q.isdigit():
                    pos_q = sec_to_mmss(pos_q)
                if dur_q.isdigit():
                    dur_q = sec_to_mmss(dur_q)
                name_part = " - ".join(x for x in (artist_q, title_q) if x)
                time_part = ""
                if pos_q and dur_q:
                    time_part = f"{pos_q} / {dur_q}"
                elif pos_q:
                    time_part = pos_q
                elif dur_q:
                    time_part = f"0:00 / {dur_q}"
                parts = []
                if name_part:
                    parts.append(name_part)
                if time_part:
                    parts.append(time_part)
                display = " | ".join(parts) if parts else "No song playing"
            else:
                artist = (parsed.get('artist') or parsed.get('album_artist') or parsed.get('name') or '').strip()
                title = (parsed.get('title') or parsed.get('name') or '').strip()
                pos = (parsed.get('position') or parsed.get('position-sec') or parsed.get('position_sec') or '').strip()
                dur = (parsed.get('duration') or parsed.get('duration-sec') or parsed.get('duration_sec') or '').strip()
                # convert seconds strings
                if pos.isdigit():
                    pos = sec_to_mmss(pos)
                if dur.isdigit():
                    dur = sec_to_mmss(dur)

                name_part = " - ".join(x for x in (artist, title) if x)
                time_part = ''
                if pos and dur:
                    time_part = f"{pos} / {dur}"
                elif pos:
                    time_part = pos
                elif dur:
                    time_part = f"0:00 / {dur}"

                parts = []
                if name_part:
                    parts.append(name_part)
                if time_part:
                    parts.append(time_part)

                display = " | ".join(parts) if parts else "No song playing"

            to_print = "\r" + display + " " * max(0, prev_len - len(display))
            print(to_print, end="", flush=True)
            prev_len = len(display)
            if rpc:
                try:
                    # prefer seconds fields for timestamps
                    parsed = parse_raw_metadata(raw)
                    pos_sec = parsed.get("position-sec") or parsed.get("position_sec") or parsed.get("position")
                    dur_sec = parsed.get("duration-sec") or parsed.get("duration_sec") or parsed.get("duration")
                    start_ts = None
                    if pos_sec and str(pos_sec).isdigit():
                        start_ts = int(time.time()) - int(pos_sec)

                    details = title if 'title' in locals() and title else None
                    state = artist if 'artist' in locals() and artist else None

                    kwargs = {}

                    kwargs['activity_type'] = ActivityType.LISTENING
                    if details:
                        kwargs['details'] = details
                    if state:
                        kwargs['state'] = state
                    if start_ts:
                        kwargs['start'] = start_ts
                    # verbose logging of RPC updates
                    if RPC_DEBUG:
                        print(f"[RPC] updating with: {kwargs}", file=sys.stderr)
                    if kwargs:
                        rpc.update(**kwargs)
                        if RPC_DEBUG:
                            print("[RPC] update sent", file=sys.stderr)
                except Exception as e:
                    # keep running even if RPC update fails
                    print(f"Discord RPC update error: {e}", file=sys.stderr)
                    if RPC_DEBUG:
                        import traceback

                        traceback.print_exc(file=sys.stderr)

            if once:
                print()
                break

            time.sleep(1)
    except KeyboardInterrupt:
        print()
    finally:
        try:
            if 'rpc' in locals() and rpc:
                try:
                    if RPC_DEBUG:
                        print("[RPC] clearing activity", file=sys.stderr)
                    rpc.clear()
                    if RPC_DEBUG:
                        print("[RPC] cleared", file=sys.stderr)
                except Exception as e:
                    print(f"Discord RPC clear error: {e}", file=sys.stderr)
                    if RPC_DEBUG:
                        import traceback
                        traceback.print_exc(file=sys.stderr)
                try:
                    if RPC_DEBUG:
                        print("[RPC] closing connection", file=sys.stderr)
                    rpc.close()
                    if RPC_DEBUG:
                        print("[RPC] closed", file=sys.stderr)
                except Exception as e:
                    print(f"Discord RPC close error: {e}", file=sys.stderr)
                    if RPC_DEBUG:
                        import traceback
                        traceback.print_exc(file=sys.stderr)
        except Exception:
            pass


if __name__ == "__main__":
    subprocess.Popen(bat_path)
    main()

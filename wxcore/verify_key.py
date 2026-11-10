"""
WeChat 4.x key-extraction + decryption VERIFIER (read-only, local).

What it does, in order:
  1. Find running Weixin.exe process(es).
  2. Locate the db_storage folder under Documents/xwechat_files/<account>.
  3. Read the 16-byte salt from a small reference db (contact.db).
  4. Scan the process memory for a 32-byte SQLCipher raw key, verifying each
     candidate by SQLCipher's HMAC-SHA512 page check (no guessing, no writing).
  5. On success, decrypt message_0.db to a temporary plaintext SQLite file,
     open it read-only, and print the table list + one real message row so you
     can see end-to-end that it works.

It never writes to WeChat, never injects, never sends anything anywhere.
Requires only PROCESS_VM_READ on Weixin.exe (same user; run elevated if denied).
"""
import ctypes as C
import ctypes.wintypes as W
import os, sys, glob, struct, hashlib, hmac, tempfile, sqlite3, time, re
import multiprocessing as mp

_RUN = re.compile(rb"[^\x00]{32,}")   # runs of >=32 non-NUL bytes (random key has none)

PAGE_SIZE = 4096
RESERVE   = 80          # IV(16) + HMAC-SHA512(64)
KEY_LEN   = 32

# ---- Win32 memory reading -------------------------------------------------
k32 = C.WinDLL("kernel32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT  = 0x1000
MEM_PRIVATE = 0x20000
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40}   # RO, RW, WC, ER, ERW
PAGE_GUARD = 0x100

class MBI(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("__a1", W.DWORD),
                ("RegionSize", C.c_size_t), ("State", W.DWORD),
                ("Protect", W.DWORD), ("Type", W.DWORD), ("__a2", W.DWORD)]

k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.VirtualQueryEx.restype = C.c_size_t
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(MBI), C.c_size_t]
k32.ReadProcessMemory.restype = W.BOOL
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

def list_weixin_pids():
    TH32CS_SNAPPROCESS = 0x2
    class PE32(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", C.POINTER(C.c_ulong)), ("th32ModuleID", W.DWORD),
                    ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                    ("pcPriClassBase", C.c_long), ("dwFlags", W.DWORD), ("szExeFile", C.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pids = []
    pe = PE32(); pe.dwSize = C.sizeof(PE32)
    if k32.Process32First(snap, C.byref(pe)):
        while True:
            if pe.szExeFile.decode("ansi", "ignore").lower() == "weixin.exe":
                pids.append(pe.th32ProcessID)
            if not k32.Process32Next(snap, C.byref(pe)):
                break
    k32.CloseHandle(snap)
    return pids

MEM_PRIVATE = 0x20000

def iter_regions(h):
    addr = 0
    mbi = MBI()
    maxaddr = 0x7FFFFFFF0000
    while addr < maxaddr:
        if k32.VirtualQueryEx(h, C.c_void_p(addr), C.byref(mbi), C.sizeof(mbi)) == 0:
            break
        size = mbi.RegionSize or 0x1000
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE and not (mbi.Protect & PAGE_GUARD):
            yield mbi.BaseAddress or addr, size
        addr += size

_CHUNK = 64 << 20
_BUF = (C.c_char * _CHUNK)()       # reusable read buffer (one big ReadProcessMemory per slice)

def read_into(h, base, size):
    got = C.c_size_t(0)
    if k32.ReadProcessMemory(h, C.c_void_p(base), _BUF, size, C.byref(got)) and got.value:
        return _BUF.raw[:got.value]
    return None

# ---- SQLCipher verification ----------------------------------------------
def mac_key_for(key, salt):
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, 64)

def key_matches(key, salt, page1):
    mk = mac_key_for(key, salt)
    data = page1[16:PAGE_SIZE - 64]
    want = page1[PAGE_SIZE - 64:PAGE_SIZE]
    calc = hmac.new(mk, data + struct.pack("<I", 1), hashlib.sha512).digest()
    return calc == want

_CHUNKSZ = 64 << 20
KDF_ITER = 256000   # WeChat 4.x derives enc_key = PBKDF2(passphrase, salt, 256000)

# WCDB key descriptor in memory: an 8-byte pointer to the 32-byte passphrase,
# then 8 zero bytes, then u64 0x20 (key size = 32), then u64 0x2f.
_KEYDESC = re.compile(rb".{6}\x00{10}\x20\x00{7}\x2f\x00{7}", re.DOTALL)

# 4 x `mov rdx, imm64` (48 BA ..) then `test rax,rax` in Weixin.dll: the four
# immediates concatenated are the 32-byte internal/XOR key the passphrase is
# obfuscated with before PBKDF2.
_DLLPAT = re.compile(
    rb"\x48\xBA(.{8}).{3,8}?\x48\xBA(.{8}).{3,8}?\x48\xBA(.{8}).{3,8}?\x48\xBA(.{8}).{3,8}?\x48\x85\xC0",
    re.DOTALL)

def extract_dll_keys(dll_path):
    keys, seen = [], set()
    with open(dll_path, "rb") as f:
        data = f.read()
    pos = 0
    while True:
        i = data.find(b"\x48\xBA", pos)
        if i < 0:
            break
        m = _DLLPAT.match(data, i)
        if m:
            k = m.group(1) + m.group(2) + m.group(3) + m.group(4)
            if k not in seen:
                seen.add(k); keys.append(k)
            pos = m.end()
        else:
            pos = i + 2
    return keys

def derive_enc_key(real_pw, salt):
    return hashlib.pbkdf2_hmac("sha512", real_pw, salt, KDF_ITER, 32)

# Persistent cache of derived per-db enc_keys, keyed by passphrase+salt so a
# changed passphrase (account switch) invalidates automatically. Set by wx.py.
_ENC_CACHE_FILE = None
_enc_mem = None

def _enc_cache():
    global _enc_mem
    if _enc_mem is None:
        import json
        _enc_mem = {}
        if _ENC_CACHE_FILE and os.path.exists(_ENC_CACHE_FILE):
            try:
                _enc_mem = json.load(open(_ENC_CACHE_FILE))
            except Exception:
                _enc_mem = {}
    return _enc_mem

def derive_enc_key_cached(real_pw, salt):
    c = _enc_cache()
    k = real_pw.hex() + ":" + salt.hex()
    v = c.get(k)
    if v is not None:
        return bytes.fromhex(v)
    ek = derive_enc_key(real_pw, salt)
    c[k] = ek.hex()
    if _ENC_CACHE_FILE:
        try:
            import json
            json.dump(c, open(_ENC_CACHE_FILE, "w"))
        except Exception:
            pass
    return ek

def _real_pw(passphrase, xorkey):
    return passphrase if xorkey is None else bytes(a ^ b for a, b in zip(passphrase, xorkey))

def verify(passphrase, salt, page1, xorkey=None):
    """passphrase XOR dll-key -> PBKDF2(256000) enc_key -> page-1 HMAC check."""
    enc_key = derive_enc_key(_real_pw(passphrase, xorkey), salt)
    mac_salt = bytes(b ^ 0x3a for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, 32)
    data = page1[16:PAGE_SIZE - 64] + struct.pack("<I", 1)
    return hmac.new(mac_key, data, hashlib.sha512).digest() == page1[PAGE_SIZE - 64:]

def read_at(h, addr, n):
    buf = (C.c_char * n)()
    got = C.c_size_t(0)
    if k32.ReadProcessMemory(h, C.c_void_p(addr), buf, n, C.byref(got)) and got.value >= n:
        return buf.raw[:n]
    return None

def is_potential_key(k):
    if len(k) != KEY_LEN or len(set(k)) < 15:
        return False
    return sum(32 <= b <= 126 for b in k) <= 24

def collect_candidates(pid):
    """Match the WCDB key-descriptor struct, follow its pointer, collect the
    (still XOR-obfuscated) 32-byte passphrase candidates, entropy-filtered."""
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"    pid {pid}: OpenProcess failed -- need admin?")
        return set()
    t0 = time.time()
    matches, tried = 0, set()
    cands = set()
    buf = (C.c_char * _CHUNKSZ)()
    got = C.c_size_t(0)
    for base, size in iter_regions(h):
        off = 0
        while off < size:
            want = min(size - off, _CHUNKSZ)
            if not k32.ReadProcessMemory(h, C.c_void_p(base + off), buf, want, C.byref(got)) or not got.value:
                break
            data = buf.raw[:got.value]
            for m in _KEYDESC.finditer(data):
                matches += 1
                ptr = struct.unpack_from("<Q", data, m.start())[0]
                if not (0x10000 <= ptr < 0x7FFFFFFFFFFF) or ptr in tried:
                    continue
                tried.add(ptr)
                pw = read_at(h, ptr, KEY_LEN)
                if pw and is_potential_key(pw):
                    cands.add(pw)
            if got.value < want:
                break
            off += got.value
    k32.CloseHandle(h)
    print(f"    pid {pid}: {matches} descriptor matches -> {len(cands)} candidates ({time.time()-t0:.1f}s)")
    return cands

_VT = None  # (salt, page1) for pool workers

def _vt_init(salt, page1):
    global _VT
    _VT = (salt, page1)

def _vt(task):
    pw, xorkey = task
    salt, page1 = _VT
    return (pw, xorkey) if verify(pw, salt, page1, xorkey) else None

def find_key(pids, salt, page1, xorkeys):
    cands = set()
    for pid in pids:
        cands |= collect_candidates(pid)
    if not cands:
        return None
    trials = [(pw, None) for pw in cands]            # some builds don't XOR
    for xk in xorkeys:
        trials += [(pw, xk) for pw in cands]
    print(f"  verifying {len(cands)} candidates x {len(xorkeys)+1} key variants = {len(trials)} trials ...")
    t0 = time.time()
    nproc = min(os.cpu_count() or 4, 12)
    with mp.Pool(nproc, initializer=_vt_init, initargs=(salt, page1)) as pool:
        for res in pool.imap_unordered(_vt, trials, chunksize=8):
            if res:
                pool.terminate()
                pw, xk = res
                print(f"  found in {time.time()-t0:.1f}s (xor={'yes' if xk else 'no'})")
                return _real_pw(pw, xk)
    print(f"  no match ({time.time()-t0:.1f}s)")
    return None

# ---- decryption -----------------------------------------------------------
def _load_aes():
    try:
        from Crypto.Cipher import AES
        return ("pycryptodome", AES)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return ("cryptography", (Cipher, algorithms, modes))
    except ImportError:
        return (None, None)

def _aes_cbc_decrypt(backend, lib, key, iv, data):
    if backend == "pycryptodome":
        return lib.new(key, lib.MODE_CBC, iv).decrypt(data)
    Cipher, algorithms, modes = lib
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()

def decrypt_db(passphrase, raw, backend, lib):
    salt = raw[:16]
    enc_key = derive_enc_key_cached(passphrase, salt)   # per-db key derivation (cached)
    npages = len(raw) // PAGE_SIZE
    out = bytearray()
    for p in range(npages):
        page = raw[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
        start = 16 if p == 0 else 0
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]
        body = page[start:PAGE_SIZE - RESERVE]
        dec = _aes_cbc_decrypt(backend, lib, enc_key, iv, body)
        if p == 0:
            out += b"SQLite format 3\x00" + dec + page[PAGE_SIZE - RESERVE:PAGE_SIZE]
        else:
            out += dec + page[PAGE_SIZE - RESERVE:PAGE_SIZE]
    return bytes(out)

def read_file_shared(path):
    # WeChat keeps the db open; open with full share mode so we can read it.
    GENERIC_READ = 0x80000000
    FILE_SHARE = 0x1 | 0x2 | 0x4
    OPEN_EXISTING = 3
    k32.CreateFileW.restype = W.HANDLE
    k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    h = k32.CreateFileW(path, GENERIC_READ, FILE_SHARE, None, OPEN_EXISTING, 0x80, None)
    if h == W.HANDLE(-1).value:
        with open(path, "rb") as f:
            return f.read()
    size = os.path.getsize(path)
    buf = (C.c_char * size)()
    got = W.DWORD(0)
    k32.ReadFile(h, buf, size, C.byref(got), None)
    k32.CloseHandle(h)
    return buf.raw[:got.value]

# ---- main -----------------------------------------------------------------
def find_db_storage():
    for root in (os.path.join(os.path.expanduser("~"), "Documents", "xwechat_files"),):
        for acct in glob.glob(os.path.join(root, "*")):
            dbs = os.path.join(acct, "db_storage")
            if os.path.isdir(dbs):
                return dbs
    return None

def find_weixin_dll():
    bases = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tencent", "Weixin"),
             os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Tencent", "Weixin")]
    best = None
    for b in bases:
        for p in glob.glob(os.path.join(b, "*", "Weixin.dll")) + glob.glob(os.path.join(b, "Weixin.dll")):
            if os.path.isfile(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                best = p
    return best

def main():
    dbs = find_db_storage()
    if not dbs:
        print("db_storage not found"); return
    print("db_storage:", dbs)
    ref = os.path.join(dbs, "contact", "contact.db")
    if not os.path.exists(ref):
        cand = glob.glob(os.path.join(dbs, "*", "*.db"))
        ref = cand[0]
    raw_ref = read_file_shared(ref)
    salt = raw_ref[:16]
    page1 = raw_ref[:PAGE_SIZE]
    print(f"reference db: {os.path.basename(ref)}  salt={salt.hex()}")

    def working_set(pid):
        psapi = C.WinDLL("psapi")
        class PMC(C.Structure):
            _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD),
                        ("PeakWorkingSetSize", C.c_size_t), ("WorkingSetSize", C.c_size_t),
                        ("QuotaPeakPagedPoolUsage", C.c_size_t), ("QuotaPagedPoolUsage", C.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", C.c_size_t), ("QuotaNonPagedPoolUsage", C.c_size_t),
                        ("PagefileUsage", C.c_size_t), ("PeakPagefileUsage", C.c_size_t)]
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return 0
        pmc = PMC(); pmc.cb = C.sizeof(PMC)
        psapi.GetProcessMemoryInfo(h, C.byref(pmc), pmc.cb)
        k32.CloseHandle(h)
        return pmc.WorkingSetSize

    # Extract the DLL XOR-key candidates from Weixin.dll (passphrase is obfuscated with it).
    xorkeys = []
    dll = find_weixin_dll()
    if dll:
        print(f"Weixin.dll: {dll}")
        try:
            xorkeys = extract_dll_keys(dll)
            print(f"  {len(xorkeys)} DLL xor-key candidate(s)")
        except Exception as e:
            print(f"  DLL scan failed: {e}")
    else:
        print("Weixin.dll not found; will try without XOR only")

    pids = list_weixin_pids()
    pids.sort(key=working_set, reverse=True)
    print("Weixin.exe PIDs (by memory):", [(p, working_set(p) >> 20) for p in pids])
    key = find_key(pids, salt, page1, xorkeys)
    if not key:
        print("\nKEY NOT FOUND. (Try running elevated, or WeChat not fully loaded.)")
        return
    print("\n==> KEY FOUND & VERIFIED. effective passphrase:", key.hex())

    # Prove decryption on the real message store.
    msg = glob.glob(os.path.join(dbs, "message", "message_0.db"))
    msg = msg[0] if msg else None
    if not msg:
        print("message_0.db not found; key is still verified above."); return
    backend, lib = _load_aes()
    if not backend:
        print("\nKey is verified. (Install pycryptodome or cryptography to also show a decrypted message.)")
        return
    raw_msg = read_file_shared(msg)
    plain = decrypt_db(key, raw_msg, backend, lib)
    if plain[:16] != b"SQLite format 3\x00":
        print("decrypt check failed"); return
    tmp = os.path.join(tempfile.gettempdir(), "wxcore_verify_message.db")
    with open(tmp, "wb") as f:
        f.write(plain)
    con = sqlite3.connect(tmp)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"\n==> DECRYPTED message_0.db OK. {len(tables)} tables.")
    # find the biggest table and show one row (truncated)
    best, bestn = None, -1
    for t in tables:
        try:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception:
            n = 0
        if n > bestn:
            best, bestn = t, n
    print(f"    largest table: {best} ({bestn} rows)")
    if best:
        cols = [d[1] for d in con.execute(f'PRAGMA table_info("{best}")')]
        row = con.execute(f'SELECT * FROM "{best}" LIMIT 1').fetchone()
        print("    columns:", cols)
        if row:
            shown = []
            for c, v in zip(cols, row):
                s = v if isinstance(v, (int, float)) else (str(v)[:60] if v is not None else None)
                shown.append(f"{c}={s!r}")
            print("    sample row:", "  ".join(shown))
    con.close()
    os.remove(tmp)
    print("\nVERIFIED: key extraction + decryption work on this WeChat build.")

if __name__ == "__main__":
    main()

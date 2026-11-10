"""Core helpers built on the verified key extraction in verify_key.py:
passphrase caching, DB decryption, and zstd message decompression."""
import os, sys, glob, sqlite3, tempfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_key as vk
import zstandard

_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "ChatRelay")
_CACHE = os.path.join(_DIR, "passphrase.hex")
vk._ENC_CACHE_FILE = os.path.join(_DIR, "enckeys.json")   # persist derived enc_keys

def get_passphrase(verbose=True):
    """Return the 32-byte effective passphrase, from cache or by extracting once."""
    if os.path.exists(_CACHE):
        try:
            return bytes.fromhex(open(_CACHE).read().strip())
        except Exception:
            pass
    dbs = vk.find_db_storage()
    ref = os.path.join(dbs, "contact", "contact.db")
    raw = vk.read_file_shared(ref)
    salt, page1 = raw[:16], raw[:vk.PAGE_SIZE]
    dll = vk.find_weixin_dll()
    xks = vk.extract_dll_keys(dll) if dll else []
    if verbose:
        print(f"[*] extracting key (dll keys={len(xks)}) ...")
    pids = vk.list_weixin_pids()
    key = vk.find_key(pids, salt, page1, xks)
    if key:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        open(_CACHE, "w").write(key.hex())
    return key

def decrypt_to_sqlite(db_path, out_path=None):
    """Decrypt a WCDB file to a plaintext SQLite file; return its path."""
    raw = vk.read_file_shared(db_path)
    backend, lib = vk._load_aes()
    if not backend:
        raise RuntimeError("need cryptography or pycryptodome for AES")
    plain = vk.decrypt_db(get_passphrase(), raw, backend, lib)
    if plain[:16] != b"SQLite format 3\x00":
        raise RuntimeError(f"decrypt failed for {db_path}")
    if not out_path:
        out_path = os.path.join(tempfile.gettempdir(),
                                "wxcore_" + os.path.basename(db_path))
    with open(out_path, "wb") as f:
        f.write(plain)
    return out_path

_zd = zstandard.ZstdDecompressor()

def unzstd(blob):
    """Decompress a WeChat message_content/compress blob; passthrough if not zstd."""
    if not blob:
        return ""
    if isinstance(blob, str):
        return blob
    if blob[:4] == b"\x28\xb5\x2f\xfd":
        try:
            return _zd.decompress(blob).decode("utf-8", "replace")
        except Exception:
            try:
                return _zd.decompressobj().decompress(blob).decode("utf-8", "replace")
            except Exception:
                return ""
    try:
        return blob.decode("utf-8", "replace")
    except Exception:
        return ""

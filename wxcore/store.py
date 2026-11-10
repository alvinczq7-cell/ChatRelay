"""ChatRelay store: decrypt WeChat 4.x WCDB, resolve names, render messages, and
build a local plaintext full-text index that the MCP server queries.

All data stays on this machine. Read-only with respect to WeChat.
"""
import os, sys, re, glob, sqlite3, hashlib, html, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx

OUT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "ChatRelay")
INDEX_DB = os.path.join(OUT_DIR, "index.db")

# base message type (low 32 bits) -> short label for non-text messages
TYPE_LABEL = {
    3: "[图片]", 34: "[语音]", 42: "[名片]", 43: "[视频]", 47: "[表情]",
    48: "[位置]", 49: "[链接/文件]", 10000: "[系统]", 10002: "[撤回]",
}
_GROUP_PREFIX = re.compile(r"^[0-9A-Za-z_\-@.]+:\n")
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def _text_of(local_type, content):
    """Render a message's displayable text."""
    base = local_type & 0xFFFFFFFF
    if base == 1:
        return _GROUP_PREFIX.sub("", content, count=1).strip()
    body = _GROUP_PREFIX.sub("", content, count=1)
    if base in (49, 244, 57) or base >= 49 and "<appmsg" in body:
        m = _TITLE.search(body)
        if m:
            return "[链接/文件] " + html.unescape(m.group(1).strip())
    return TYPE_LABEL.get(base, f"[类型{base}]")


class Store:
    def __init__(self):
        self.dbs = wx.vk.find_db_storage()
        if not self.dbs:
            raise RuntimeError("WeChat db_storage not found")
        acct_dir = os.path.basename(os.path.dirname(self.dbs))
        self.own_wxid = re.sub(r"_[^_]+$", "", acct_dir)
        self._dec = {}          # db file -> sqlite connection (decrypted temp)
        self.contact_name = {}  # wxid -> display name
        self._load_contacts()
        self._load_sessions_meta()
        self._load_message_dbs()

    # -- decryption / connections ------------------------------------------
    def _conn(self, rel_or_path):
        path = rel_or_path
        if not os.path.isabs(path):
            hits = glob.glob(os.path.join(self.dbs, "*", os.path.basename(rel_or_path)))
            if not hits:
                return None
            path = hits[0]
        if path not in self._dec:
            tmp = wx.decrypt_to_sqlite(path, os.path.join(OUT_DIR, "dec_" + os.path.basename(path)))
            c = sqlite3.connect(tmp)
            c.text_factory = bytes
            self._dec[path] = c
        return self._dec[path]

    @staticmethod
    def _s(v):
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else ("" if v is None else str(v))

    # -- loaders -----------------------------------------------------------
    def _load_contacts(self):
        c = self._conn("contact.db")
        for uname, remark, nick in c.execute("SELECT username, remark, nick_name FROM contact"):
            u = self._s(uname)
            self.contact_name[u] = self._s(remark) or self._s(nick) or u
        # chat room member nicknames (sender names inside groups)
        self.room_member = {}
        try:
            for room, member, nick in c.execute(
                    "SELECT room_username, member_username, nick_name FROM chatroom_member"):
                self.room_member[(self._s(room), self._s(member))] = self._s(nick)
        except Exception:
            pass

    def _load_sessions_meta(self):
        self.sessions = []
        c = self._conn("session.db")
        for uname, ts, unread, summary in c.execute(
                "SELECT username, sort_timestamp, unread_count, summary FROM SessionTable "
                "ORDER BY sort_timestamp DESC"):
            u = self._s(uname)
            if u.endswith("sessionholder"):
                continue
            self.sessions.append({
                "username": u, "name": self.name_of(u),
                "is_group": u.endswith("@chatroom"),
                "timestamp": ts, "unread": unread, "summary": self._s(summary),
            })

    def _load_message_dbs(self):
        self.table_db = {}   # Msg_<md5> -> (conn, name2id list)
        for f in sorted(glob.glob(os.path.join(self.dbs, "message", "message_*.db"))):
            if not re.match(r"^message_\d+\.db$", os.path.basename(f)):
                continue  # skip message_fts.db / message_resource.db etc.
            c = self._conn(f)
            n2i = [None] + [self._s(r[0]) for r in c.execute("SELECT user_name FROM Name2Id ORDER BY rowid")]
            for (name,) in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg\\_%' ESCAPE '\\'"):
                self.table_db[self._s(name)] = (c, n2i)

    # -- helpers -----------------------------------------------------------
    def name_of(self, wxid):
        return self.contact_name.get(wxid, wxid)

    def _table_for(self, username):
        return "Msg_" + hashlib.md5(username.encode()).hexdigest()

    def resolve_username(self, name_or_id):
        """Accept a wxid/@chatroom, a display name, or a remark; return username."""
        if name_or_id in self.contact_name or name_or_id.endswith("@chatroom"):
            return name_or_id
        for s in self.sessions:
            if s["name"] == name_or_id or s["username"] == name_or_id:
                return s["username"]
        for u, n in self.contact_name.items():
            if n == name_or_id:
                return u
        low = name_or_id.lower()
        for s in self.sessions:
            if low in s["name"].lower():
                return s["username"]
        return None

    def _sender_name(self, username, is_group, sender_id, n2i, content):
        wxid = n2i[sender_id] if 0 < sender_id < len(n2i) else ""
        if wxid == self.own_wxid:
            return "我"
        if is_group:
            nm = self.room_member.get((username, wxid))
            if nm:
                return nm
        return self.name_of(wxid) if wxid else "?"

    # -- queries -----------------------------------------------------------
    def list_sessions(self, limit=30):
        return self.sessions[:limit]

    def get_history(self, name_or_id, limit=30, before_ts=None):
        u = self.resolve_username(name_or_id)
        if not u:
            return None, []
        tab = self._table_for(u)
        entry = self.table_db.get(tab)
        if not entry:
            return u, []
        con, n2i = entry
        is_group = u.endswith("@chatroom")
        where = "WHERE create_time < ?" if before_ts else ""
        args = (before_ts,) if before_ts else ()
        rows = con.execute(
            f'SELECT create_time, real_sender_id, local_type, message_content FROM "{tab}" '
            f'{where} ORDER BY sort_seq DESC LIMIT ?', (*args, limit)).fetchall()
        out = []
        for ct, sid, lt, mc in reversed(rows):
            content = wx.unzstd(mc)
            out.append({
                "time": ct,
                "sender": self._sender_name(u, is_group, sid, n2i, content),
                "text": _text_of(lt, content),
            })
        return u, out

    # -- full-text index (all messages + sessions + contacts snapshots) ----
    def build_index(self, progress=None):
        os.makedirs(OUT_DIR, exist_ok=True)
        ix = sqlite3.connect(INDEX_DB)
        ix.execute("CREATE TABLE IF NOT EXISTS meta(conv TEXT PRIMARY KEY, last_ts INTEGER)")
        # plain table + LIKE: robust for Chinese substring search (FTS5 unicode61
        # does not tokenize CJK; trigram needs >=3 chars).
        ix.execute("CREATE TABLE IF NOT EXISTS msg("
                   "conv TEXT, conv_name TEXT, sender TEXT, text TEXT, ts INTEGER, type INTEGER)")
        ix.execute("CREATE INDEX IF NOT EXISTS ix_ts ON msg(ts)")
        ix.execute("CREATE INDEX IF NOT EXISTS ix_conv ON msg(conv, ts)")
        # snapshots so the server can serve reads without decrypting anything
        ix.execute("CREATE TABLE IF NOT EXISTS sessions("
                   "username TEXT PRIMARY KEY, name TEXT, is_group INT, ts INTEGER, unread INT, summary TEXT)")
        ix.execute("CREATE TABLE IF NOT EXISTS contacts(wxid TEXT PRIMARY KEY, name TEXT)")
        ix.execute("DELETE FROM sessions")
        ix.executemany("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?)",
                       [(s["username"], s["name"], int(s["is_group"]), s["timestamp"],
                         s["unread"], s["summary"]) for s in self.sessions])
        ix.execute("DELETE FROM contacts")
        ix.executemany("INSERT OR REPLACE INTO contacts VALUES(?,?)", list(self.contact_name.items()))

        total = 0
        for s in self.sessions:
            u = s["username"]
            tab = self._table_for(u)
            entry = self.table_db.get(tab)
            if not entry:
                continue
            con, n2i = entry
            is_group = u.endswith("@chatroom")
            last = ix.execute("SELECT last_ts FROM meta WHERE conv=?", (u,)).fetchone()
            last_ts = last[0] if last else 0
            rows = con.execute(
                f'SELECT create_time, real_sender_id, local_type, message_content FROM "{tab}" '
                f'WHERE create_time > ? ORDER BY create_time', (last_ts,)).fetchall()
            newmax = last_ts
            batch = []
            for ct, sid, lt, mc in rows:
                content = wx.unzstd(mc)
                batch.append((u, s["name"],
                              self._sender_name(u, is_group, sid, n2i, content),
                              _text_of(lt, content), ct, lt & 0xFFFFFFFF))
                newmax = max(newmax, ct or 0)
            if batch:
                ix.executemany(
                    "INSERT INTO msg(conv,conv_name,sender,text,ts,type) VALUES(?,?,?,?,?,?)", batch)
                total += len(batch)
            ix.execute("INSERT INTO meta(conv,last_ts) VALUES(?,?) "
                       "ON CONFLICT(conv) DO UPDATE SET last_ts=excluded.last_ts", (u, newmax))
            if progress:
                progress(s["name"], len(batch))
        ix.commit()
        ix.close()
        return total

    def list_files(self, limit=50):
        return _list_files(self.dbs, limit)


def _list_files(dbs, limit=50):
    root = os.path.normpath(os.path.join(dbs, "..", "msg", "file"))
    files = []
    for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        if os.path.isfile(p):
            files.append((os.path.getmtime(p), p))
    files.sort(reverse=True)
    return [{"path": p, "name": os.path.basename(p), "mtime": int(mt),
             "size": os.path.getsize(p)} for mt, p in files[:limit]]


class Index:
    """Read-only view over index.db. Serves every query WITHOUT decrypting any
    WeChat database — only Store.build_index() (called by refresh) decrypts."""

    def __init__(self):
        self.con = sqlite3.connect(INDEX_DB)
        self.con.row_factory = sqlite3.Row
        self._dbs = None  # resolved lazily, only for list_files

    @staticmethod
    def ready():
        if not os.path.exists(INDEX_DB):
            return False
        c = sqlite3.connect(INDEX_DB)
        try:
            return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone() is not None
        finally:
            c.close()

    def list_sessions(self, limit=30):
        rows = self.con.execute(
            "SELECT username, name, is_group, ts, unread, summary FROM sessions "
            "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"username": r["username"], "name": r["name"], "is_group": bool(r["is_group"]),
                 "timestamp": r["ts"], "unread": r["unread"], "summary": r["summary"]} for r in rows]

    def resolve_username(self, name_or_id):
        if name_or_id.endswith("@chatroom"):
            return name_or_id
        r = self.con.execute("SELECT username FROM sessions WHERE username=? OR name=? LIMIT 1",
                             (name_or_id, name_or_id)).fetchone()
        if r:
            return r[0]
        r = self.con.execute("SELECT wxid FROM contacts WHERE wxid=? OR name=? LIMIT 1",
                             (name_or_id, name_or_id)).fetchone()
        if r:
            return r[0]
        r = self.con.execute("SELECT username FROM sessions WHERE name LIKE ? ORDER BY ts DESC LIMIT 1",
                             ("%" + name_or_id + "%",)).fetchone()
        return r[0] if r else None

    def get_history(self, name_or_id, limit=40, before_ts=None):
        u = self.resolve_username(name_or_id)
        if not u:
            return None, []
        where = "conv=?" + (" AND ts < ?" if before_ts else "")
        args = (u, before_ts) if before_ts else (u,)
        rows = self.con.execute(
            f"SELECT ts, sender, text FROM msg WHERE {where} ORDER BY ts DESC LIMIT ?",
            (*args, limit)).fetchall()
        hist = [{"time": r["ts"], "sender": r["sender"], "text": r["text"]} for r in reversed(rows)]
        return u, hist

    def search(self, keyword, limit=30, conv=None):
        like = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql = ("SELECT conv_name, sender, text, ts FROM msg WHERE text LIKE ? ESCAPE '\\' "
               + ("AND conv=? " if conv else "") + "ORDER BY ts DESC LIMIT ?")
        args = (like, conv, limit) if conv else (like, limit)
        rows = self.con.execute(sql, args).fetchall()
        return [{"conv": r["conv_name"], "sender": r["sender"], "text": r["text"], "time": r["ts"]} for r in rows]

    def list_contacts(self, query="", limit=40):
        if query:
            rows = self.con.execute(
                "SELECT wxid, name FROM contacts WHERE wxid NOT LIKE '%@chatroom' AND name LIKE ? LIMIT ?",
                ("%" + query + "%", limit)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT wxid, name FROM contacts WHERE wxid NOT LIKE '%@chatroom' LIMIT ?", (limit,)).fetchall()
        return [{"wxid": r["wxid"], "name": r["name"]} for r in rows]

    def list_files(self, limit=50):
        if self._dbs is None:
            self._dbs = wx.vk.find_db_storage()
        return _list_files(self._dbs, limit)

"""ChatRelay MCP server — read-only access to your own WeChat chat history + files,
for Claude / Codex / Cursor. All local; nothing is uploaded.

Tools: list_sessions, get_history, search, list_contacts, list_files, refresh.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
from store import Store, Index

mcp = FastMCP("chatrelay")
_index = None

def store():
    """Return a read-only Index. Builds it once (decrypting) if missing; afterwards
    every query is served from index.db with no decryption."""
    global _index
    if _index is None:
        if not Index.ready():
            Store().build_index()
        _index = Index()
    return _index

def _rebuild():
    global _index
    Store().build_index()   # decrypt latest DBs + incrementally update the index
    _index = Index()

def _t(ts):
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"

@mcp.tool()
def list_sessions(limit: int = 30) -> str:
    """List your most recent WeChat conversations (newest first), with name,
    whether it is a group, unread count and last-active time."""
    out = []
    for s in store().list_sessions(limit):
        kind = "group" if s["is_group"] else "chat"
        out.append(f"{_t(s['timestamp'])} | {kind} | {s['name']} | unread={s['unread']}")
    return "\n".join(out) or "(no sessions)"

@mcp.tool()
def get_history(conversation: str, limit: int = 40, before: str = "") -> str:
    """Read recent messages of one conversation. `conversation` is a contact/group
    display name or id. `before` optional 'YYYY-MM-DD' to page backwards."""
    before_ts = None
    if before:
        try:
            before_ts = int(datetime.datetime.strptime(before, "%Y-%m-%d").timestamp())
        except ValueError:
            return "before must be YYYY-MM-DD"
    u, hist = store().get_history(conversation, limit, before_ts)
    if u is None:
        return f"conversation not found: {conversation}"
    if not hist:
        return f"(no messages for {conversation})"
    return "\n".join(f"[{_t(m['time'])}] {m['sender']}: {m['text']}" for m in hist)

@mcp.tool()
def search(keyword: str, limit: int = 30, conversation: str = "") -> str:
    """Full-text search your message history for a keyword. Optionally restrict to
    one conversation (display name or id)."""
    conv = None
    if conversation:
        conv = store().resolve_username(conversation)
        if not conv:
            return f"conversation not found: {conversation}"
    res = store().search(keyword, limit, conv)
    if not res:
        return "(no matches)"
    return "\n".join(f"[{_t(r['time'])}] {r['conv']} / {r['sender']}: {r['text']}" for r in res)

@mcp.tool()
def list_contacts(query: str = "", limit: int = 40) -> str:
    """List/search your contacts by name (substring match on remark/nickname)."""
    out = [f"{c['name']} | {c['wxid']}" for c in store().list_contacts(query, limit)]
    return "\n".join(out) or "(no contacts)"

@mcp.tool()
def list_files(limit: int = 30) -> str:
    """List files you received in WeChat (newest first) with local path and size."""
    out = []
    for f in store().list_files(limit):
        out.append(f"{_t(f['mtime'])} | {f['size']//1024}KB | {f['name']} | {f['path']}")
    return "\n".join(out) or "(no files)"

@mcp.tool()
def refresh() -> str:
    """Re-decrypt the latest WeChat databases and update the local index with new
    messages. Run this to pick up messages received since the server started."""
    _rebuild()
    return "refreshed"

if __name__ == "__main__":
    mcp.run()

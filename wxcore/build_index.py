"""Standalone index builder: decrypt the WeChat DBs and (re)build the local
index once, from the command line. Handy for first-time setup or a manual
rebuild without the MCP server running. The server builds in-process; it does
not shell out to this.

    python build_index.py        # requires consent (see consent.py)

Prints a one-line status to stderr; exit code 0 on success.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from consent import require_consent
from store import Store

if __name__ == "__main__":
    require_consent()
    s = Store()
    try:
        n = s.build_index()
    finally:
        s.close()
    sys.stderr.write("indexed %d messages\n" % n)

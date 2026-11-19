import sqlite3
import sys

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "data/app.db")
db.row_factory = sqlite3.Row
print("--- model_profiles")
try:
    for r in db.execute("select key, kind, upstream_model, enabled, capabilities from model_profiles"):
        print(dict(r))
except Exception as e:  # noqa: BLE001
    print("err", e)
print("--- app_settings (model/image)")
for r in db.execute(
    "select key, value from app_settings where key like '%model%' or key like '%image%'"
    " or key like '%budget%'"
):
    print(dict(r))

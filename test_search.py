import os
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
for q in ["vegetarian food green colour symbol", "non-vegetarian brown symbol labelling", "nutraceutical label declaration health supplement"]:
    try:
        rows = sb.rpc("search_library", {"q": q, "n": 3}).execute().data
    except Exception as e:
        print(q, "-> ERROR:", e)
        continue
    print(f"\n{q} -> {len(rows)} results")
    for r in rows:
        print("  ", r["file"].rsplit("/", 1)[-1], "| p.", r["page"], "|", r["text"][:100].replace("\n", " "))
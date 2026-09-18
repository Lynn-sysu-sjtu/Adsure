from __future__ import annotations
import argparse, json, shutil, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path

ACTIVE={"queued","processing"}
def age_days(ts):
    try: return (datetime.now(timezone.utc)-datetime.fromisoformat(ts)).total_seconds()/86400
    except Exception: return 0

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data/video_service")
    p.add_argument("--success-days", type=float, default=30)
    p.add_argument("--failed-days", type=float, default=14)
    p.add_argument("--dry-run", action="store_true")
    args=p.parse_args(); root=Path(args.data_dir); db=root/"jobs.sqlite3"
    if not db.exists(): return
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    removed=[]
    for row in con.execute("select job_id,status,updated_at from jobs"):
        if row["status"] in ACTIVE: continue
        limit=args.success_days if row["status"]=="completed" else args.failed_days
        if age_days(row["updated_at"]) < limit: continue
        path=root/"jobs"/row["job_id"]; upload=root/"uploads"/(row["job_id"]+".mp4")
        removed.append(str(path))
        if not args.dry_run:
            shutil.rmtree(path, ignore_errors=True)
            upload.unlink(missing_ok=True)
            con.execute("delete from jobs where job_id=?", (row["job_id"],))
    con.commit(); con.close()
    log=root/"cleanup.log"; log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a",encoding="utf-8") as f:
        for item in removed: f.write(datetime.now(timezone.utc).isoformat()+" "+item+"\n")
    print(json.dumps({"removed":len(removed),"dry_run":args.dry_run},ensure_ascii=False))
if __name__=="__main__": main()

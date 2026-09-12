"""Mechanically migrate a user-supplied key out of a tracked example, without logging it."""
from pathlib import Path
import os

ROOT=Path(__file__).resolve().parents[1]


def parse(path):
    values={}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key,value=line.split("=",1)
            values[key.strip()]=value.strip().strip('"\'')
    return values


def migrate():
    source=ROOT/".env.example"
    destination=ROOT/".env.video.local"
    old=parse(source)
    existing=parse(destination)
    key=old.get("API_KEY") or old.get("VIDEO_MVP_CLOUD_API_KEY") or old.get("OPENAI_API_KEY","")
    if not key or key in {"YOUR_API_KEY","<your-api-key>",""}:
        print("No new key to migrate")
        return
    if existing.get("VIDEO_MVP_CLOUD_API_KEY") and existing["VIDEO_MVP_CLOUD_API_KEY"]!=key:
        raise RuntimeError("A different private key already exists; refusing to overwrite")
    existing.update(VIDEO_MVP_VLM_PROVIDER="cloud",VIDEO_MVP_CLOUD_API_KEY=key,
                    VIDEO_MVP_CLOUD_BASE_URL=old.get("BASE_URL",old.get("VIDEO_MVP_CLOUD_BASE_URL","")))
    existing.setdefault("VIDEO_MVP_CLOUD_MODEL",old.get("MODEL",""))
    existing.setdefault("VIDEO_MVP_CLOUD_CONSENT","0")
    existing.setdefault("VIDEO_MVP_CLOUD_ALLOWED_VIDEO_SHA256","")
    # This is a mechanical secret migration; retain all unrelated user configuration.
    descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,"w") as handle:
        handle.write("# 本机私密配置，禁止提交。云端外发默认关闭。\n")
        for name,value in existing.items():
            handle.write(name+"="+value+"\n")
    os.chmod(destination,0o600)
    if parse(destination).get("VIDEO_MVP_CLOUD_API_KEY") != key:
        raise RuntimeError("Private configuration read-back failed")
    lines=[]
    for line in source.read_text().splitlines():
        name=line.split("=",1)[0].strip()
        if name in {"API_KEY","OPENAI_API_KEY","VIDEO_MVP_CLOUD_API_KEY"} and "=" in line:
            line=name+"=YOUR_API_KEY"
        lines.append(line)
    source.write_text("\n".join(lines)+"\n")
    print("Key migrated to .env.video.local (mode 0600); example sanitized; external-data consent remains disabled.")


if __name__=="__main__":
    migrate()

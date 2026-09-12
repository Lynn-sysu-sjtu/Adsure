"""Send only a generated geometric test image, never a user video/document."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from src.video_mvp.cloud_config import config
from src.video_mvp.semantics import analyze_scenes

if __name__ == "__main__":
    out=Path("tmp/video_mvp/cloud-synthetic-smoke")
    out.mkdir(parents=True,exist_ok=True)
    image=np.full((256,256,3),255,dtype=np.uint8)
    cv2.rectangle(image,(60,60),(196,196),(0,0,255),-1)
    frame=out/"synthetic-red-square.jpg"
    cv2.imwrite(str(frame),image)
    r=analyze_scenes([{"frameId":"synthetic_red_square","timestamp":0.,"imagePath":str(frame.resolve())}],
        out,video_sha256="synthetic_no_user_video",consent_endpoint=config().endpoint)
    print(json.dumps({"input":"synthetic_red_square_only_no_user_data","status":r["status"],
                      "observations":r["observations"],"errors":r["errors"]},ensure_ascii=False,indent=2))

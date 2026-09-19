#!/usr/bin/env python3
"""Generate a tiny valid MP4 with OpenCV for repeatable smoke tests."""
from pathlib import Path
import argparse, cv2, numpy as np

def main():
 p=argparse.ArgumentParser(); p.add_argument("--output",default="tests/fixtures/sample_ad.mp4"); p.add_argument("--frames",type=int,default=12)
 args=p.parse_args(); out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
 writer=cv2.VideoWriter(str(out),cv2.VideoWriter_fourcc(*"mp4v"),6,(320,240))
 if not writer.isOpened(): raise SystemExit("cannot create video writer")
 for i in range(args.frames):
  img=np.full((240,320,3),245,np.uint8)
  cv2.putText(img,f"frame {i}",(20,60),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
  cv2.putText(img,"sample ad",(20,150),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,180),2)
  writer.write(img)
 writer.release(); print(out, out.stat().st_size)
if __name__=="__main__": main()

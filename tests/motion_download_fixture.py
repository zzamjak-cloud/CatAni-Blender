"""네트워크 없이 다운로드와 Blender 가져오기를 연결하는 합성 BVH."""

import io


BVH_BYTES = b"""HIERARCHY
ROOT Hips
{
 OFFSET 0 0 0
 CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
 End Site
 {
  OFFSET 0 1 0
 }
}
MOTION
Frames: 2
Frame Time: 0.0416667
0 0 0 0 0 0
0 0 0 5 0 0
"""


class MemoryResponse(io.BytesIO):
    """urlopen 응답 대신 메모리의 고정 바이트를 제공한다."""

    def __init__(self, payload=BVH_BYTES):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self.status = 200

    def getcode(self):
        return self.status

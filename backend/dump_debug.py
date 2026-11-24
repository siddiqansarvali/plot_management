import asyncio, winocr
from PIL import Image

async def run():
    img = Image.open('uploads/WhatsApp_Image_2026-10-11_at_22_09_42_db77e790-36b8-4777-8e4e-33702f9c0abc.jpeg')
    res = await winocr.recognize_pil(img)
    print(f"Total lines in original: {len(res.lines)}")
    for line in res.lines:
        b = line.words[0].bounding_rect if line.words else None
        pos = f"at ({b.x:.0f}, {b.y:.0f})" if b else ""
        print(f"{line.text!r:45} {pos}")

asyncio.run(run())

"""Source-independent pixel rulers. No chart readings or baseline values."""
from PIL import Image, ImageDraw, ImageFont

def coordinate_grid(source, destination, spacing=100):
    image=Image.open(source).convert('RGB')
    draw=ImageDraw.Draw(image)
    font=ImageFont.load_default(size=14)
    for x in range(0,image.width,spacing):
        draw.line((x,0,x,image.height-1),fill=(110,180,225),width=1)
    for y in range(0,image.height,spacing):
        draw.line((0,y,image.width-1,y),fill=(110,180,225),width=1)
        for x in range(0,image.width,spacing):
            label=f'{x},{y}'
            box=draw.textbbox((x+2,y+2),label,font=font)
            draw.rectangle(box,fill='white')
            draw.text((x+2,y+2),label,font=font,fill=(0,70,160))
    image.save(destination)
    return destination

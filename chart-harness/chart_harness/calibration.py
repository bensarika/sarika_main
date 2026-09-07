"""One bounded calibration retry with enlarged raw tick strips, no prior values."""
from pathlib import Path
from PIL import Image


def recheck_packet(image_path, plot_bbox, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        im = source.convert('RGB')
        w, h = im.size
        l, t, r, b = map(int, plot_bbox)
        boxes = {
            'x_ticks': (max(0,l-35), max(0,b-15), min(w,r+35), h),
            'y_ticks': (0, max(0,t-30), min(w,l+20), min(h,b+30)),
        }
        images, descriptions = [], []
        for name, box in boxes.items():
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            tile = im.crop(box)
            tile = tile.resize((tile.width*3,tile.height*3),Image.Resampling.NEAREST)
            path = outdir/(name+'.png')
            tile.save(path)
            images.append(path)
            descriptions.append({'image_index':len(images)+1, 'region':name,
                'source_crop_box':list(box), 'scale':3,
                'pixel_mapping':'original = crop_origin + (tile_pixel + 0.5)/3 - 0.5'})
    prompt = f'''Independently read numerical axis calibration from the raw chart.
Image 1 defines the coordinate frame: {w}x{h}, top-left pixel center (0,0).
The next images are nearest-neighbor enlargements of RAW tick strips; they add
no information or reconstructed glyphs. Their transforms: {descriptions}.
Any subsequent images provide the shared axes/legend. Some panels omit y labels.
Return JSON {{"axis_check":{{"x_axis":{{"scale":"linear or log","unit":"printed unit",
"anchors":[{{"pixel":original_image_coordinate,"value":printed_tick_value}},...]}},
"y_axis":{{"scale":"linear or log","unit":"printed unit","anchors":[...]}}}},
"status":"readable or unresolved","notes":[]}}.
Read actual digits, not an expected sampling schedule or conventional tick values.
Use at least two well-separated printed ticks per axis, preferably three or more.
Coordinates MUST refer to image 1, not to enlarged strips or other context images.
Explicit breaks require separate segments. allow_extrapolation=true only for a
visibly unbroken extension beyond outer labeled ticks. If unreadable, status must
be unresolved; do not guess. Do not supply point values or run code.'''
    return prompt, [Path(image_path)] + images

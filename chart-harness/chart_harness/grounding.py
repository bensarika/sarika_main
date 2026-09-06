"""Meta image-understanding adapter; normalized coordinates, exact sent image basis."""
import copy, math

def pixel(value, extent):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Coordinate must be finite')
    if not -5 <= value <= 1005: raise ValueError('Coordinate outside normalized frame')
    return min(extent-1,max(0,round(value*extent/1000)))

def to_native(reading,width,height):
    out=copy.deepcopy(reading)
    out['plot_bbox']=[pixel(v,e) for v,e in zip(out['plot_bbox'],[width,height,width,height])]
    for key,extent in [('x_axis',width),('y_axis',height)]:
        for a in out[key]['anchors']: a['pixel']=pixel(a['pixel'],extent)
    for s in out['series']:
        for p in s['seeds']: p.update(x=pixel(p['x'],width),y=pixel(p['y'],height))
        if 'template_bbox' in s:s['template_bbox']=[pixel(v,e) for v,e in zip(s['template_bbox'],[width,height,width,height])]
    return out

PROMPT='''Locate every observed data marker in this chart. Return JSON with plot_bbox:[left,top,right,bottom], x_axis and y_axis each {scale:"linear" or "log",unit:"printed unit or empty string",anchors:[{pixel:coordinate,value:printed numerical tick value}]}, series:[{id:"s1",label:"printed legend label",marker:"ring" or "template",template_bbox:[left,top,right,bottom],seeds:[{x:integer,y:integer}]}], notes:[], unresolved_regions:[]. All location fields including pixel, boxes and seeds MUST use normalized 0–1000 coordinates relative to this single image, top-left (0,0), x right, y down. Read at least three actual printed ticks on each axis where available. Point to every marker before counting. Omit objects you cannot find; distinguish observations from predicted lines, error bars and legend symbols. Do not invent hidden markers or units. Template boxes enclose one clean marker only. Do not calculate concentrations. Return only JSON.'''

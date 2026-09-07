"""Refine model-supplied tick locations using raster stroke evidence.

Never changes tick values or invents axes. Rejects missing/ambiguous evidence.
"""
import copy
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

def _peak_near(profile, guess, reach=60):
    lo=max(0,int(guess-reach));hi=min(len(profile),int(guess+reach+1))
    if hi<=lo:raise ValueError('Empty axis search window')
    window=profile[lo:hi]
    peak=int(np.argmax(window))+lo
    if profile[peak]<=0:raise ValueError('No stroke evidence near proposed axis')
    return peak

def refine_axes(image, interpretation):
    d=copy.deepcopy(interpretation)
    ink=1-np.asarray(Image.open(image).convert('L'),dtype=float)/255
    h,w=ink.shape;l,t,r,b=map(int,d['plot_bbox'])
    # Long-axis projections are independent of any previous extraction.
    v=gaussian_filter1d(ink[max(0,t+30):min(h,b-30)].mean(axis=0),1)
    x=_peak_near(v,l)
    horizontal=gaussian_filter1d(ink[:,min(w,x+40):min(w,r-20)].mean(axis=1),1)
    bottom=_peak_near(horizontal,b)
    tick_x=gaussian_filter1d(ink[min(h,bottom+3):min(h,bottom+23)].mean(axis=0),1)
    tick_x[:max(0,x-4)]=0
    # Detect long y ticks, or plot-wide grid lines when those are present.
    inside=ink[:,min(w,x+30):min(w,r-20)].mean(axis=1)
    grid_peaks,_=find_peaks(gaussian_filter1d(inside,1),distance=12,prominence=.05,height=.22)
    grids=[int(p) for p in grid_peaks if max(0,t-60)<=p<=bottom+3]
    if len(grids)>=4:
        yp=gaussian_filter1d(inside,1);mode='plot_grid_lines'
        peaks=grids
    else:
        yp=gaussian_filter1d(ink[:,max(0,x-70):max(1,x-4)].mean(axis=1),1)
        candidates,_=find_peaks(yp,distance=12)
        region=[int(p) for p in candidates if max(0,t-60)<=p<=bottom+3]
        threshold=max(yp[p] for p in region)*.72
        peaks=[p for p in region if yp[p]>=threshold];mode='long_tick_strokes'
    log={'vertical_axis_x':x,'horizontal_axis_y':bottom,'y_evidence_mode':mode,'y_candidates':peaks,'anchors':[]}
    for name in ('x_axis','y_axis'):
        a=d[name]; a['unit']=a.get('unit') or ''
        refined=[]
        for old in a['anchors']:
            if name=='x_axis':
                pos=_peak_near(tick_x,old['pixel'],55)
                strength=float(tick_x[pos])
                if strength<.04:raise ValueError('Insufficient x tick evidence')
            else:
                options=[p for p in peaks if abs(p-old['pixel'])<=60]
                if not options:
                    log['anchors'].append({'axis':name,'original':old,'action':'withheld_no_long_tick_or_grid_evidence'})
                    continue
                pos=min(options,key=lambda p:abs(p-old['pixel']));strength=float(yp[pos])
            refined.append({'pixel':pos,'value':old['value']})
            log['anchors'].append({'axis':name,'original':old,'refined_pixel':pos,'strength':strength})
        if len(refined)<2 or len({v['pixel'] for v in refined})!=len(refined):
            raise ValueError(f'Insufficient distinct raster-supported anchors: {name}, {refined}, evidence={peaks}, mode={mode}, axes={x},{bottom}')
        a['anchors']=refined
        # Preserve the model's prior explicit axis domain, not arbitrary outer space.
        if name=='y_axis' and len(refined)<len(interpretation[name]['anchors']):
            a['allow_extrapolation']=bool(interpretation[name].get('allow_extrapolation',False))
            d.setdefault('unresolved_regions',[]).append({'reason':'A proposed outer tick lacks long-stroke evidence. No new extrapolation permission was inferred; requires review.'})
    d['plot_bbox']=[max(0,x-35),max(0,t-20),min(w,max(r,x+1)+40),min(h,bottom+5)]
    return d,log

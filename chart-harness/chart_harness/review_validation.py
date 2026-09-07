"""A model's affirmative classification cannot substitute for location agreement."""
import copy,math

# Agreement is judged against the size of the mark being pointed at, measured by
# python when the candidate was refined: naming the centre of a 3 px dot and of a
# 40 px ring are not the same claim, and no single pixel count fits both. Only
# when nothing about the mark was measured does the candidate's own recorded
# pixel uncertainty stand in.
CENTER_FRACTION_OF_MARK = .5

def mark_radius(candidate):
 """Half the extent of the mark under a candidate, from whatever measured it."""
 d=candidate.get('diagnostics') or {}
 if isinstance(d.get('rx'),(int,float)) and isinstance(d.get('ry'),(int,float)):
  return max(float(d['rx']),float(d['ry']))
 box=d.get('component_bbox') or d.get('template_bbox')
 if isinstance(box,(list,tuple)) and len(box)==4:
  scale=d.get('scale') if isinstance(d.get('scale'),(int,float)) and d.get('scale')>0 else 1.
  return max(float(box[2])-float(box[0]),float(box[3])-float(box[1]))*float(scale)/2.
 u=candidate.get('pixel_uncertainty') or {}
 if isinstance(u.get('x'),(int,float)) and isinstance(u.get('y'),(int,float)):
  return math.hypot(float(u['x']),float(u['y']))
 return None

def enforce_marker_centers(review,proposals,fraction=CENTER_FRACTION_OF_MARK):
 if isinstance(fraction,bool) or not isinstance(fraction,(int,float)) or not math.isfinite(fraction) or not 0<fraction<=1:raise ValueError('Review center agreement must be a fraction of the mark in (0, 1]')
 review=copy.deepcopy(review);by_id={p['candidate_id']:p for p in proposals['candidates']}
 review['marker_center_checks']=[]
 for d in review.get('decisions',[]):
  center=d.pop('marker_center',{});d.pop('center_discrepancy_px',None)
  if d.get('role')!='observed':continue
  candidate=by_id.get(d.get('candidate_id'));p=candidate['pixel'] if candidate else None
  valid=p and isinstance(center,dict) and all(isinstance(center.get(k),(int,float)) and not isinstance(center.get(k),bool) and math.isfinite(center[k]) for k in ['x','y'])
  distance=math.hypot(center['x']-p['x'],center['y']-p['y']) if valid else None
  radius=mark_radius(candidate) if candidate else None
  tolerance=None if radius is None else radius*fraction
  review['marker_center_checks'].append({'candidate_id':d.get('candidate_id'),'reported_center':center,
    'distance_px':distance,'mark_radius_px':radius,'tolerance_px':tolerance})
  if distance is None or tolerance is None or distance>tolerance:
   d['role']='unresolved';review['status']='review_required'
   d['reason']='Independent marker center missing or differs from fixed candidate; '+d.get('reason','')
 return review

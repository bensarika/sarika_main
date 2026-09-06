"""A model's affirmative classification cannot substitute for location agreement."""
import copy,math

def enforce_marker_centers(review,proposals,tolerance=2.0):
 if isinstance(tolerance,bool) or not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or not 0<tolerance<=2:raise ValueError('Review center tolerance must be in (0, 2] pixels')
 review=copy.deepcopy(review);points={p['candidate_id']:p['pixel'] for p in proposals['candidates']}
 review['marker_center_checks']=[]
 for d in review.get('decisions',[]):
  center=d.pop('marker_center',{});d.pop('center_discrepancy_px',None)
  if d.get('role')!='observed':continue
  p=points.get(d.get('candidate_id'))
  valid=p and isinstance(center,dict) and all(isinstance(center.get(k),(int,float)) and not isinstance(center.get(k),bool) and math.isfinite(center[k]) for k in ['x','y'])
  distance=math.hypot(center['x']-p['x'],center['y']-p['y']) if valid else None
  review['marker_center_checks'].append({'candidate_id':d.get('candidate_id'),'reported_center':center,'distance_px':distance})
  if distance is None or distance>tolerance:
   d['role']='unresolved';review['status']='review_required'
   d['reason']='Independent marker center missing or differs from fixed candidate; '+d.get('reason','')
 return review

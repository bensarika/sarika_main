"""CLI and restartable state machine; model responses are never executable."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image
from .ingest import inspect_document, render_page, crop_image
from . import geometry
from .prompts import (interpret_prompt,review_axes_prompt,review_batch_prompt,
  cross_judge_prompt,CROSS_JUDGE_SCHEMA,
  INTERPRET_SCHEMA,REVIEW_AXES_SCHEMA,REVIEW_BATCH_SCHEMA,VERSION)
from .provider import ModelConfig,Provider,ReplayProvider,ExchangeProvider,PendingResponse
from .audit import usage_report, export_batch
from .calibration import recheck_packet
from . import axis_detect
from . import doc_context
from . import duel
from . import frame_fit
from .consensus import compare
from .coordinate_grid import coordinate_grid
from .visual_check import VisualCheckProvider
from .review_validation import enforce_marker_centers
from . import review_batches
from . import markers
from . import marker_screen
from . import progress

def write_json(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(data,indent=2,allow_nan=False));tmp.replace(path)

def make_provider(config,out,role):
 return VisualCheckProvider(_make_provider(config,out,role),out/"visual_checks"/role,
   strict=config.get('visual_check_strict',True))

def _make_provider(config,out,role):
 c=dict(config.get(role,config['model']))
 mode=c.pop('mode',config.get('mode','api'))
 artifact=out/'calls'/role
 limits=config.get('limits',{})
 if mode=='exchange':
  return ExchangeProvider(out/'exchange'/role,artifact_dir=artifact,
                          max_calls=limits.get('max_calls',6))
 if mode=='replay':
  return ReplayProvider(c.pop('responses'),artifact_dir=artifact)
 return Provider(ModelConfig(**c),artifact_dir=artifact,
   max_calls=limits.get('max_calls',6),
   max_estimated_cost_usd=limits.get('max_estimated_cost_usd'),
   max_reserved_output_tokens=limits.get('max_reserved_output_tokens',30000),
   max_retries=limits.get('max_retries',0))

def provider_label(config):
 """Short name for whose reading an artifact represents, stamped on overlays."""
 if config.get('provider_label'):return str(config['provider_label'])
 model=config.get('model',{})
 return str(model.get('model') or model.get('mode') or config.get('mode','model'))

TRANSPORT_KEYS=('timeout_s','max_retries')

def semantic_config(config):
 """Config without transport-only settings, so retry/timeout tuning keeps completed stages."""
 def strip(value):
  if isinstance(value,dict):
   return {k:strip(v) for k,v in value.items() if k not in TRANSPORT_KEYS}
  if isinstance(value,list):
   return [strip(v) for v in value]
  return value
 return strip(config)

def orient(source,out,clockwise):
 with Image.open(source) as src:
  im=src.convert('RGB');w,h=im.size
  transforms={0:np.eye(3),90:np.array([[0,1,0],[-1,0,h-1],[0,0,1]]),
   180:np.array([[-1,0,w-1],[0,-1,h-1],[0,0,1]]),
   270:np.array([[0,-1,w-1],[1,0,0],[0,0,1]])}
  if clockwise not in transforms:raise ValueError('rotation must be 0,90,180,270')
  if clockwise: im=im.rotate(-clockwise,expand=True)
  im.save(out)
 return transforms[clockwise]

def bounded_context(path,query,limit):
 if not path:return ''
 text=Path(path).read_text(errors='replace')
 terms=[s.lower() for s in query.split() if len(s)>2]
 paragraphs=text.split('\n')
 scored=sorted(enumerate(paragraphs),key=lambda p:sum(t in p[1].lower() for t in terms),reverse=True)
 selected=[];total=0
 for index,line in scored:
  if not line.strip():continue
  chunk=line[:min(1800,limit-total)]
  selected.append((index,chunk));total+=len(chunk)
  if total>=limit:break
 return '\n'.join(v for _,v in sorted(selected))[:limit]

def source_context(args,config,source):
 """Words about the figure: a supplied file, else the document's own text."""
 limit=config.get('context_chars',6000)
 supplied=bounded_context(args.context_file,args.query,limit)
 if supplied or Path(source).suffix.lower()!='.pdf':return supplied
 return doc_context.figure_context(source,args.query,getattr(args,'page',None),limit)

def validate_interpretation(d,size):
 if not isinstance(d,dict):raise ValueError('interpretation must be an object')
 if d.get('unsupported'):return
 w,h=size
 box=d.get('plot_bbox')
 if not isinstance(box,list) or len(box)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in box):
  raise ValueError('plot_bbox needs four finite numbers')
 if not(0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h):raise ValueError('plot_bbox out of frame')
 ids=set()
 for s in d.get('series',[]):
  if not isinstance(s.get('id'),str) or s['id'] in ids:raise ValueError('series IDs must be unique strings')
  ids.add(s['id'])
  if len(s.get('seeds',[]))>1000:raise ValueError('too many model seeds')
  for p in s.get('seeds',[]):
   if not all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) for k in ('x','y')):raise ValueError('nonfinite seed')
   if not(0<=p['x']<w and 0<=p['y']<h):raise ValueError('seed out of frame')
 if not ids:raise ValueError('No series supplied')

def run(args):
 start=time.monotonic();source=Path(args.source).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 config=json.loads(Path(args.config).read_text())
 signature=hashlib.sha256(source.read_bytes()+json.dumps({'config':semantic_config(config),'query':args.query,'page':args.page,
   'rotate':args.rotate,'crop':args.crop,'prompt_version':VERSION,
   'reference_image_hashes':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (
      getattr(args,'reference_images',[]) or ([args.reference_image] if getattr(args,'reference_image',None) else []))],
   'context_hash':hashlib.sha256(Path(args.context_file).read_bytes()).hexdigest() if args.context_file else None},sort_keys=True).encode()).hexdigest()
 state_path=out/'state.json'
 state=json.loads(state_path.read_text()) if state_path.exists() else {'run_signature':signature,'source':str(source),'stages':{}}
 if state['run_signature']!=signature:raise ValueError('Output directory belongs to a different input/config; choose a new --out')
 def stage(name,fn):
  p=out/(name+'.json')
  if name in state['stages'] and p.exists():
   saved=json.loads(p.read_text());check=saved.get('_visual_check')
   if not check:return saved
   visual=Path(check['image_path'])
   if visual.exists() and hashlib.sha256(visual.read_bytes()).hexdigest()==check.get('image_sha256'):
    progress.emit('stage',stage=name,state='reused',path=str(p));return saved
   # Re-render via the same provider/cache if the mandatory image was removed or changed.
  progress.emit('stage',stage=name,state='started')
  began=time.monotonic();value=fn();write_json(p,value)
  state['stages'][name]={'path':str(p),'wall_seconds':time.monotonic()-began}
  progress.emit('stage',stage=name,state='finished',seconds=round(time.monotonic()-began,1),path=str(p))
  write_json(state_path,state);return value
 context=source_context(args,config,source)
 try:
  page=args.page;rotation=args.rotate
  if source.suffix.lower()=='.pdf':
   if not page:
    manifest=stage('document',lambda:inspect_document(source,out/'document',args.query,
                        max_candidates=config.get('max_candidate_pages',24),ocr=config.get('ocr',False)))
    contact=manifest.get('contact_sheet_path')
    selector=make_provider(config,out,'locator')
    selected=stage('selection',lambda:selector.complete('locate',
      'Select the PDF page containing the requested OBSERVED PK figure. '
      'Read page labels on the contact sheet. Return JSON {"page":1-based integer,'
      '"rotation":clockwise degrees 0/90/180/270,"reason":"..."}. '
      'If unavailable return {"page":null,"reason":"..."}; do not guess. Request: '+args.query+
      '\nDocument candidates: '+json.dumps(manifest.get('candidates',[]),default=str)[:10000],
      images=[Path(contact)] if contact else []))
    page=selected.get('page');rotation=selected.get('rotation',0)
    if not page:raise ValueError('Requested figure not found among candidate pages; inspect document and increase coverage/OCR')
   raster=render_page(source,int(page),out/'page.png',dpi=config.get('render_dpi',216))
  else:raster=source
  transform=orient(raster,out/'oriented.png',rotation)
  with Image.open(out/'oriented.png') as image:w,h=image.size
  crop=args.crop or [0,0,w,h]
  info=crop_image(out/'oriented.png',crop,out/'working.png',max_side=config.get('max_image_side',2200))
  affine=transform@np.array(info['output_to_source'])
  with Image.open(raster) as original: raster_size=list(original.size)
  write_json(out/'image_manifest.json',{'source':str(source),'page':page,'rotation':rotation,
      'working_image':str(out/'working.png'),'working_to_page_raster':affine.tolist(),
      'crop':info,'page_raster_size':raster_size})
  with Image.open(out/'working.png') as image:size=image.size
  interpreter=make_provider(config,out,'model')
  references=[Path(p) for p in (getattr(args,'reference_images',[]) or ([args.reference_image] if getattr(args,'reference_image',None) else []))]
  if config.get('coordinate_grid',False):
   references.insert(0,coordinate_grid(out/'working.png',out/'coordinate_grid.png'))
   context += '\nThe blue reference grid uses the exact same pixel dimensions as image 1. Every intersection label is x,y in image 1 pixels. Use it to locate ticks and markers; do not estimate coordinates from a resized display. Read marker bodies in the original unannotated image. Grid lines are not chart data.'
  interpretation=stage('interpretation',lambda:interpreter.complete('interpret',
      interpret_prompt(*size,context,args.query)+'\nAdditional images, if any, show legend/source context. All coordinates and template boxes MUST refer to image 1.',
      images=[out/'working.png']+references,schema=INTERPRET_SCHEMA))
  validate_interpretation(interpretation,size)
  interpretation['overlay_label']=provider_label(config)
  progress.emit('legend',plot_bbox=interpretation.get('plot_bbox'),
    series=[{k:s.get(k) for k in ('id','label','marker','marker_description','colour')}
            for s in interpretation.get('series',[])],
    sample_times=interpretation.get('sample_times'),
    unresolved_regions=interpretation.get('unresolved_regions',[]),
    image=str(out/'working.png'))
  if not interpretation.get('unsupported') and config.get('detect_ticks',True):
   tick_tolerance=config.get('axis_tick_tolerance_px',6.)
   check=axis_detect.crosscheck(out/'working.png',interpretation,tick_tolerance)
   if not check['agrees'] and not check['inconclusive'] and config.get('repair_axes_from_ticks',True):
    prompt,tick_images=axis_detect.repair_packet(out/'working.png',check['detected'],out/'tick_repair')
    repaired=stage('axis_repair',lambda:interpreter.complete('axis_repair',prompt,images=tick_images+references))
    if repaired.get('status')=='readable':
     applied=axis_detect.apply_repair(interpretation,repaired,check['detected'],tick_tolerance)
     if applied:
      check=axis_detect.crosscheck(out/'working.png',interpretation,tick_tolerance)
      check['repaired_axes']=sorted(applied)
      write_json(out/'interpretation.json',interpretation)
   if not check['inconclusive'] and config.get('clamp_plot_bbox_to_axes',True):
    measured=axis_detect.plot_bbox_from_ticks(check['detected']) if config.get('plot_bbox_from_ticks',True) else None
    clamped,changed=(measured,measured!=[float(v) for v in interpretation['plot_bbox']]) if measured else \
      axis_detect.clamp_plot_bbox(interpretation['plot_bbox'],check['detected'])
    if changed:
     transform=frame_fit.fit(interpretation['plot_bbox'],clamped) if measured and config.get('rescale_model_frame',True) else None
     if transform and not frame_fit.is_identity(transform):
      interpretation,note=frame_fit.apply(interpretation,transform,size)
      check['model_frame_rescaled']=note
     check['plot_bbox_clamped_from']=interpretation['plot_bbox']
     check['plot_bbox_source']='measured_axes' if measured else 'clamped_model_box'
     interpretation['plot_bbox']=clamped
     for series in interpretation.get('series',[]):
      seeds=[s for s in series.get('seeds',[]) if clamped[0]<=s['x']<=clamped[2] and clamped[1]<=s['y']<=clamped[3]]
      if seeds!=series.get('seeds',[]):
       check.setdefault('seeds_dropped_outside_plot',{})[series['id']]=len(series.get('seeds',[]))-len(seeds)
       series['seeds']=seeds
     write_json(out/'interpretation.json',interpretation)
   interpretation['axis_tick_check']=check
   write_json(out/'axis_tick_check.json',check)
  # The legend is the one place a marker is guaranteed unobstructed, so its
  # pixels, not a reader's box, define what each series looks like.
  if not interpretation.get('unsupported') and config.get('legend_templates',True):
   glyphs=markers.extract_templates(out/'working.png',interpretation['plot_bbox'],
     [s['label'] for s in interpretation['series']],out/'legend')
   if len(glyphs)==len(interpretation['series']):
    for series,glyph in zip(interpretation['series'],glyphs):
     series['marker']='template';series['template_bbox']=glyph['template_bbox']
     series['legend_glyph']={k:glyph[k] for k in ('template_path','ink_fraction','width','height')}
     series.pop('seeds',None)
    write_json(out/'interpretation.json',interpretation)
    progress.emit('legend_glyphs',glyphs=[{'label':s['label'],**s['legend_glyph']}
      for s in interpretation['series']])
   else:
    progress.emit('legend_glyphs',glyphs=[],reason='legend glyph column not measurable')
    write_json(out/'legend'/'unmatched.json',{'labels':[s['label'] for s in interpretation['series']],
      'glyphs_found':len(glyphs),'reason':'legend glyph column not measurable; falling back to reader marks'})
  # Acceptance tolerance belongs to user configuration, never to the model.
  interpretation['axis_tolerance_fraction']=config.get('axis_tolerance_fraction',0.005)
  interpretation['pixel_tolerance']=config.get('pixel_tolerance',1.)
  for series in interpretation.get('series',[]):
   if series.get('marker')=='ring':series['coarse_ring_search']=config.get('coarse_ring_search',True)
   if series.get('marker')=='template':
    series['match_threshold']=max(series.get('match_threshold',0.72),config.get('min_template_score',0.6))
  if interpretation.get('unsupported'):
   result={'status':'unsupported','reason':interpretation.get('reason'),'points':[]}
   write_json(out/'result.json',result);return result
  proposals=stage('proposals',lambda:geometry.analyze(out/'working.png',interpretation,out/'geometry'))
  # A proposal is only meaningful as a reading of the figure, so it is reported in
  # the figure's own units and against the group it was attributed to; the pixels
  # stay alongside because they are what the screen re-measures.
  axes={}
  for name in ('x_axis','y_axis'):
   try:axes[name]=geometry.Axis(interpretation.get(name),name)
   except Exception:axes[name]=None
  labels={s['id']:s.get('label',s['id']) for s in interpretation.get('series',[])}
  def reading(c):
   sid=c.get('series_id') or (c.get('possible_series') or [None])[0]
   groups=[labels.get(s,s) for s in (c.get('possible_series') or ([sid] if sid else []))]
   return {'candidate_id':c['candidate_id'],'series':sid,
           'series_label':labels.get(sid),'possible_groups':groups,
           'x':axes['x_axis'].value(c['pixel']['x']) if axes['x_axis'] else None,
           'y':axes['y_axis'].value(c['pixel']['y']) if axes['y_axis'] else None,
           'x_unit':interpretation.get('x_axis',{}).get('unit'),
           'y_unit':interpretation.get('y_axis',{}).get('unit'),
           'pixel_x':c['pixel']['x'],'pixel_y':c['pixel']['y'],'score':c.get('score')}
  progress.emit('candidates',count=len(proposals['candidates']),
    candidates=[reading(c) for c in proposals['candidates']],
    overlay=proposals.get('overlay_path'))
  # No legend, or a legend of words only: the marks are still on the page, so a
  # search target is mined from the proposals themselves rather than dropping
  # the pixel screen, which would let unmeasured coordinates through.
  if (config.get('screen_candidates_against_legend',True)
      and not any(s.get('template_bbox') for s in interpretation['series'])):
   mined=[]
   for series in interpretation['series']:
    points=[c['pixel'] for c in proposals['candidates']
            if series['id'] in ([c.get('series_id')] if c.get('series_id') else c.get('possible_series',[]))]
    target=markers.mine_templates(out/'working.png',points,out/'legend'/series['id']) if points else None
    if target:
     series['template_bbox']=target['template_bbox']
     series['legend_glyph']={**{k:target[k] for k in ('template_path','ink_fraction','width','height')},
                             'mined_from_plot':True}
     mined.append({'label':series['label'],**series['legend_glyph']})
   write_json(out/'interpretation.json',interpretation)
   progress.emit('legend_glyphs',glyphs=mined,
     reason='no legend glyphs; targets mined from the plot itself' if mined
            else 'no legend glyphs and no measurable mark under any proposal')
  reviewer=make_provider(config,out,'reviewer')
  # Review is split so no single call carries the whole figure: calibration once,
  # then a few candidates per crop of the original pixels, each call bounded.
  labels=[s['label'] for s in interpretation['series']]
  detected=(interpretation.get('axis_tick_check') or {}).get('detected') or {}
  axes_review=stage('review_axes',lambda:reviewer.complete('review_axes',
       review_axes_prompt(labels,context,detected),images=[out/'working.png']+references,
       schema=REVIEW_AXES_SCHEMA))
  if detected and isinstance(axes_review.get('axis_check'),dict):
   axis_check,dropped=axis_detect.resolve_tick_indices(axes_review['axis_check'],detected,
     config.get('axis_tick_tolerance_px',6.))
   axes_review={**axes_review,'axis_check':axis_check}
   if dropped:axes_review['notes']=list(axes_review.get('notes',[]))+[
     f'review anchors ignored, they name no measured tick: {json.dumps(dropped)}']
   write_json(out/'review_axes_resolved.json',axes_review)
  batches=review_batches.plan(proposals['candidates'],size,
    batch_size=config.get('review_batch_size',review_batches.BATCH_SIZE),
    padding_px=config.get('review_batch_padding_px',review_batches.PADDING_PX),
    min_side=config.get('review_batch_min_side_px',review_batches.MIN_SIDE))
  write_json(out/'review_batches.json',batches)
  parts=[]
  gray=markers.load_gray(out/'working.png') if config.get('screen_candidates_against_legend',True) else None
  templates={s['id']:s['template_bbox'] for s in interpretation['series'] if s.get('template_bbox')}
  by_candidate={c['candidate_id']:c for c in proposals['candidates']}
  for batch in batches:
   crop_path=review_batches.crop(out/'working.png',batch,out/'review_batches')
   with Image.open(crop_path) as im:crop_size=im.size
   measurements=marker_screen.batch_feedback(gray,templates,batch,by_candidate) if gray is not None else None
   parts.append(stage(f"review_batch_{batch['index']:03d}",
     lambda batch=batch,crop_path=crop_path,crop_size=crop_size,measurements=measurements:reviewer.complete(
       f"review_batch_{batch['index']:03d}",
       review_batch_prompt(batch,labels,crop_size,context,measurements,
         config.get('judging_provider_label')),
       images=[crop_path],schema=REVIEW_BATCH_SCHEMA)))
  review=review_batches.merge(axes_review,parts,batches)
  write_json(out/'review.json',review)
  review=enforce_marker_centers(review,proposals,config.get('review_center_tolerance_px',2.0))
  write_json(out/'review_center_checks.json',review.get('marker_center_checks',[]))
  # Review uses printed labels, rather than inheriting the first reader's assignments.
  label_to_id={s['label']:s['id'] for s in interpretation['series']}
  for decision in review.get('decisions',[]):
   if decision.get('series_id') in label_to_id:decision['series_id']=label_to_id[decision['series_id']]
   series=next((s for s in interpretation['series'] if s['id']==decision.get('series_id')),None)
   if (series and series.get('marker')=='point' and decision.get('role')=='observed'
       and not config.get('allow_unrefined_points',False)):
    decision['role']='unresolved'
    decision['reason']='Unrefined model coordinates require explicit user opt-in; '+decision.get('reason','')
  # Pixel evidence outranks assignment: a decision may name a series, it may not
  # decide that ink exists. Failures are measured, not argued.
  if config.get('screen_candidates_against_legend',True):
   screens=marker_screen.apply(out/'working.png',interpretation,proposals,review,
     min_ncc=config.get('screen_min_ncc',markers.DEFAULT_MATCH_THRESHOLD),
     min_ink_ratio=config.get('screen_min_ink_ratio',.5))
   write_json(out/'candidate_screen.json',screens)
   progress.emit('screen',checked=len(screens),
     failed=sum(1 for s in screens if not s.get('passed')),
     corrected=sum(1 for s in screens if s.get('corrected')),results=screens[:200])
   if any(s.get('corrected') for s in screens):write_json(out/'proposals.json',proposals)
  result=geometry.finalize(out/'working.png',interpretation,proposals,review,out/'final')
  if (config.get('recheck_axes',True) and result.get('axis_agreement') and
      not all(v['accepted'] for v in result['axis_agreement'].values())):
   prompt,tick_images=recheck_packet(out/'working.png',interpretation['plot_bbox'],out/'tick_recheck')
   calibrator=make_provider(config,out,'calibrator')
   checked=stage('calibration_recheck',lambda:calibrator.complete('calibration_recheck',
       prompt,images=tick_images+references))
   if checked.get('status')=='readable' and isinstance(checked.get('axis_check'),dict):
    revised_review={**review,'axis_check':checked['axis_check']}
    first_agreement=result['axis_agreement']
    result=geometry.finalize(out/'working.png',interpretation,proposals,revised_review,out/'final')
    result['initial_axis_agreement']=first_agreement
    result['calibration_recheck_used']=True
  # Entire-job completeness is stricter than candidate precision.
  unresolved=interpretation.get('unresolved_regions',[])
  if unresolved or review.get('missing_points') or review.get('status')!='accepted':
   result['status']='review_required'
  result['unresolved_regions']=unresolved
  if 'axis_tick_check' in interpretation:result['axis_tick_check']=interpretation['axis_tick_check']
  result['model_mode']=config.get('mode',config.get('model',{}).get('mode','api'))
  result['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
  result['wall_seconds_this_invocation']=time.monotonic()-start
  result['notes']=list(result.get('notes',[]))+[
    'Pixel coordinates refer to working.png. image_manifest.json maps them to the source page raster.',
    'Model agreement and overlay fit do not establish original numerical ground truth.',
    'Missing observations are not reconstructed; unresolved regions prevent whole-chart acceptance.']
  checked=stage('final_visual_check',lambda:interpreter.check('final_output',result,[out/'working.png']))
  result['_visual_check']=checked['_visual_check']
  if (result['_visual_check']['assessment']=='concerns' or interpretation.get('_visual_check',{}).get('assessment')=='concerns' or review.get('_visual_check',{}).get('assessment')=='concerns'):result['status']='review_required'
  result['visual_checks']=[str(p) for p in sorted((out/'visual_checks').rglob('*.png'))]
  write_json(out/'result.json',result)
  write_json(result['json_path'],result)
  progress.emit('result',status=result['status'],counts=result.get('counts',{}),
    rows=result.get('rows',[])[:400],overlay=result.get('overlay_path'),
    unresolved_regions=result.get('unresolved_regions',[]),output_dir=str(out))
  print(json.dumps({'status':result['status'],'result':str(out/'result.json'),'output_dir':str(out)}))
  return result
 except PendingResponse as e:
  write_json(state_path,state)
  print(str(e));return {'status':'awaiting_model_response','request':str(e.request_path),'response':str(e.response_path)}

def batch(args):
 """Locate once, split panels once, then execute the same two stages per panel."""
 source=Path(args.source).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 config=json.loads(Path(args.config).read_text());locator=make_provider(config,out,'locator')
 signature=hashlib.sha256(source.read_bytes()+json.dumps({'config':semantic_config(config),'query':args.query,
   'page':args.page,'rotate':args.rotate,'prompt_version':VERSION,
   'context_hash':hashlib.sha256(Path(args.context_file).read_bytes()).hexdigest() if args.context_file else None},sort_keys=True).encode()).hexdigest()
 identity_path=out/'batch_state.json'
 if identity_path.exists() and json.loads(identity_path.read_text())['run_signature']!=signature:
  raise ValueError('Output directory belongs to a different input/config; choose a new --out')
 write_json(identity_path,{'run_signature':signature,'source':str(source)})
 try:
  if source.suffix.lower()=='.pdf':
   page=args.page
   if not page:
    mp=out/'document'/'manifest.json'
    manifest=json.loads(mp.read_text()) if mp.exists() else inspect_document(source,out/'document',args.query,
      max_candidates=config.get('max_candidate_pages',24),ocr=config.get('ocr',False))
    choices=[{k:c.get(k) for k in ('page_number','score','text_snippet')} for c in manifest['candidates']]
    selected=locator.complete('locate','Choose the page with the requested observed PK graph, using page numbers in the contact sheet. '
       'Return JSON {"page":integer,"reason":"..."}; null page if not found. '
       'Request: '+args.query+'\n'+json.dumps(choices),images=[Path(manifest['contact_sheet_path'])])
    page=selected.get('page')
    if not page:raise ValueError('No requested figure located; increase candidate coverage or enable OCR')
   native=render_page(source,int(page),out/'selected_page.png',dpi=config.get('render_dpi',216))
  else:page=None;native=source
  context=source_context(args,config,source)
  rotation=args.rotate
  def read_layout(stage,clockwise):
   """Lay the page out at this rotation; the sheet itself may be printed sideways."""
   transform=orient(native,out/'oriented_page.png',clockwise)
   with Image.open(out/'oriented_page.png') as im:size=im.size
   view=crop_image(out/'oriented_page.png',[0,0,size[0],size[1]],out/'layout_view.png',max_side=2200)
   with Image.open(out/'layout_view.png') as im:preview_size=im.size
   pw,ph=preview_size
   read=locator.complete(stage,f'''Identify distinct requested PK panels in this page ({pw}x{ph} pixels).
Request: {args.query}
Return JSON {{"panels":[{{"id":"iv","label":"IV","crop_bbox":[left,top,right,bottom]}}],
"legend_bbox":[left,top,right,bottom],"page_rotation_clockwise":0,"notes":[]}}.
Boxes use the supplied image. Panel crops must include axis ticks/units but exclude
neighboring plot interiors. A shared legend is cropped separately. If there is
only one panel return one. Maximum {config.get('max_panels',4)} panels. Never
include predicted/simulated panels when the request is observed measurements.
Patent and journal sheets are often printed sideways: if the axis labels and title
read sideways, set page_rotation_clockwise to the degrees (90, 180 or 270) this
image must be rotated clockwise to stand upright; the page is then rotated and the
boxes asked for again. Set it to 0 when the plot already stands upright.
Return an empty panels list if the requested figure is absent. Source evidence:
{context}''',images=[out/'layout_view.png'])
   return read,transform,size,view,preview_size
  layout,page_transform,(w,h),preview,(pw,ph)=read_layout('layout',rotation)
  turn=layout.get('page_rotation_clockwise')
  if rotation==0 and turn in (90,180,270):
   progress.emit('reorient',clockwise=turn,reason='sheet printed sideways')
   rotation=turn
   layout,page_transform,(w,h),preview,(pw,ph)=read_layout('layout_upright',rotation)
  progress.emit('layout',panels=[{'id':p.get('id'),'label':p.get('label')}
    for p in layout.get('panels',[]) if isinstance(p,dict)],image=str(out/'layout_view.png'))
  if not isinstance(layout.get('panels'),list) or not 1<=len(layout['panels'])<=config.get('max_panels',4):
   raise ValueError('No supported panels, or panel count exceeds configured bound')
  scale=np.array(preview['output_edges_to_source_edges'])
  def native_box(box):
   if len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):raise ValueError('invalid panel box')
   if not(0<=box[0]<box[2]<=pw and 0<=box[1]<box[3]<=ph):raise ValueError('panel box outside image')
   a=scale@np.array([box[0],box[1],1]);b=scale@np.array([box[2],box[3],1])
   return [max(0,int(math.floor(a[0]))),max(0,int(math.floor(a[1]))),min(w,int(math.ceil(b[0]))),min(h,int(math.ceil(b[1])))]
  ref=None
  if layout.get('legend_bbox'):
   ref=out/'legend.png';crop_image(out/'oriented_page.png',native_box(layout['legend_bbox']),ref)
  write_json(out/'layout.json',{'source':str(source),'page':page,'rotation':rotation,'layout':layout,'preview_transform':preview})
  results=[];used=set()
  for panel in layout['panels']:
   pid=panel.get('id')
   if not isinstance(pid,str) or not pid.replace('_','').replace('-','').isalnum() or pid in used:raise ValueError('unsafe or duplicate panel ID')
   used.add(pid)
   sub=argparse.Namespace(source=str(out/'oriented_page.png'),config=args.config,out=str(out/'panels'/pid),
      query=args.query+'; panel: '+str(panel.get('label',pid)),page=None,rotate=0,
      crop=native_box(panel['crop_bbox']),context_file=args.context_file,reference_image=None,
      reference_images=([str(ref)] if ref else [])+[str(out/'layout_view.png')])
   progress.emit('panel',panel=pid,label=str(panel.get('label',pid)),state='started')
   r=run(sub)
   progress.emit('panel',panel=pid,label=str(panel.get('label',pid)),state='finished',
     status=r.get('status'))
   if r.get('rows') is not None:
    ip=out/'panels'/pid/'image_manifest.json'
    im=json.loads(ip.read_text())
    original_transform=page_transform@np.asarray(im['working_to_page_raster'])
    im.update({'original_source':str(source),'original_pdf_page':page,
               'working_to_original_page_raster':original_transform.tolist()})
    write_json(ip,im)
    for row in r['rows']:
     point=original_transform@np.array([row['pixel_x'],row['pixel_y'],1.])
     row['page_pixel_x']=float(point[0]);row['page_pixel_y']=float(point[1])
    write_json(out/'panels'/pid/'result.json',r)
    write_json(r['json_path'],r)
   results.append({'panel':pid,**r})
  status='awaiting_model_response' if any(r['status']=='awaiting_model_response' for r in results) else (
      'accepted' if all(r['status']=='accepted' for r in results) else 'review_required')
  result={'status':status,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'page':page,'panels':results}
  if status!='awaiting_model_response':result['exports']=export_batch(result,out)
  result['usage']=usage_report(out)
  write_json(out/'usage_summary.json',result['usage'])
  write_json(out/'batch_result.json',result);print(json.dumps({'status':status,'result':str(out/'batch_result.json')}))
  return result
 except PendingResponse as e:
  print(str(e));return {'status':'awaiting_model_response','request':str(e.request_path),'response':str(e.response_path)}

def panel_comparison(left,right):
 """Compare two batch runs panel by panel; panels only one side found are kept."""
 def panels(root):return {p.name:p for p in sorted((Path(root)/'panels').glob('*')) if (p/'result.json').exists()}
 a,b=panels(left),panels(right);shared=sorted(set(a)&set(b))
 reports={pid:compare(a[pid],b[pid]) for pid in shared}
 disagreements=[{'panel':pid,**d} for pid in shared for d in reports[pid]['disagreements']]
 for pid in sorted(set(a)^set(b)):
  disagreements.append({'panel':pid,'code':'panel_found_by_one_run_only',
    'side':'left' if pid in a else 'right'})
 return {'panels':reports,'disagreements':disagreements,'agrees':not disagreements}

def cross_judge(judge,run_dir,authored_by,context):
 """One provider judges the other's finished reading of each panel."""
 verdicts={}
 for panel in sorted((Path(run_dir)/'panels').glob('*')):
  if not (panel/'result.json').exists():continue
  summary=duel.summarize(run_dir)
  entry=next((p for p in summary['panels'] if p['panel']==panel.name),{})
  images=[panel/'working.png']
  overlay=panel/'final'/'final_overlay.png'
  if overlay.exists():images.append(overlay)
  verdicts[panel.name]=judge.complete(f'cross_judge_{panel.name}',
    cross_judge_prompt(authored_by,entry,duel.screen_digest(run_dir),context),
    images=images,schema=CROSS_JUDGE_SCHEMA)
 findings=[f for v in verdicts.values() for f in v.get('findings',[])]
 verdict=('unusable' if any(v.get('verdict')=='unusable' for v in verdicts.values())
   else 'needs_another_pass' if any(v.get('verdict')=='needs_another_pass' for v in verdicts.values())
   else 'sound')
 worst=next((v.get('worst_problem') for v in verdicts.values() if v.get('worst_problem')),'')
 return {'verdict':verdict,'worst_problem':worst,'findings':findings,'panels':verdicts,
         'judged':authored_by,'judged_by':None}

def duel_sides(config_paths):
 """The two readings to be compared, named by whose reading each one is."""
 sides=[]
 for path in config_paths:
  config=json.loads(Path(path).read_text())
  sides.append({'config_path':str(path),'config':config,'name':provider_label(config)})
 if len(sides)!=2:raise ValueError('a duel compares exactly two configs')
 return sides

def adjudicate(sides,out,context,rerun):
 """Each reader judges the other's finished work; whoever earns it runs again.

 `rerun(side, directory, context_file)` performs the extra pass, so this policy
 is the same whether the first two readings ran one after another or at once.
 """
 out=Path(out)
 first=panel_comparison(sides[0]['dir'],sides[1]['dir'])
 write_json(out/'first_comparison.json',first)
 judgments,decisions,iterations={},{},{}
 for side,other in ((sides[0],sides[1]),(sides[1],sides[0])):
  judge=make_provider(other['config'],out/'judges'/other['name'],'reviewer')
  judgments[side['name']]=cross_judge(judge,side['dir'],side['name'],context)
  judgments[side['name']]['judged_by']=other['name']
  reflection=duel.self_reflection(side['dir'])
  side['reflection']=reflection
  decisions[side['name']]=duel.decide(judgments[side['name']],reflection,first)
  progress.emit('judgment',side=side['name'],judged_by=other['name'],
    verdict=judgments[side['name']]['verdict'],
    worst_problem=judgments[side['name']]['worst_problem'],
    findings=judgments[side['name']]['findings'][:20],
    iterate=decisions[side['name']]['iterate'],
    reasons=decisions[side['name']]['reasons'])
 write_json(out/'cross_judgments.json',judgments)
 write_json(out/'decisions.json',decisions)
 for side in sides:
  decision=decisions[side['name']]
  if not decision['iterate']:continue
  feedback=out/f"feedback_{side['name']}.md"
  feedback.write_text(context+'\n\n'+duel.feedback_text(decision,judgments[side['name']]))
  directory=out/(side['name']+'_pass2')
  progress.emit('iteration',side=side['name'],state='started',
    feedback=duel.feedback_text(decision,judgments[side['name']]))
  iterations[side['name']]={'dir':str(directory),'feedback_path':str(feedback),
    'result':rerun(side,directory,str(feedback))}
  side['dir']=directory
  progress.emit('iteration',side=side['name'],state='finished',
    status=iterations[side['name']]['result'].get('status'))
 final=panel_comparison(sides[0]['dir'],sides[1]['dir']) if iterations else first
 report=duel.report({s['name']:{'dir':str(s['dir']),'reflection':s['reflection']} for s in sides},
   first,judgments,decisions,iterations,final)
 write_json(out/'duel_report.json',report)
 progress.emit('duel_report',agrees=report['agrees'],iterated=sorted(iterations),
   path=str(out/'duel_report.json'))
 return report

def duel_run(args):
 """Both readers over one figure, one after the other, then adjudication."""
 out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 source=Path(args.source).resolve()
 sides=duel_sides(args.config)
 def batch_args(side,directory,context_file=None):
  return argparse.Namespace(source=str(source),config=side['config_path'],out=str(directory),
    query=args.query,page=args.page,rotate=args.rotate,crop=None,
    context_file=context_file,reference_image=None,reference_images=[])
 for side in sides:
  side['dir']=out/side['name'];side['result']=batch(batch_args(side,side['dir']))
 report=adjudicate(sides,out,source_context(args,sides[0]['config'],source),
   lambda side,directory,context_file:batch(batch_args(side,directory,context_file)))
 print(json.dumps({'agrees':report['agrees'],'iterated':sorted(report['iterations']),
   'report':str(out/'duel_report.json')},indent=2))
 return report

def main():
 parser=argparse.ArgumentParser(description='Small-context model interpretation plus deterministic pixel digitization')
 sub=parser.add_subparsers(dest='command',required=True)
 inspect=sub.add_parser('inspect');inspect.add_argument('source');inspect.add_argument('--out',required=True)
 inspect.add_argument('--query',default='pharmacokinetic concentration time');inspect.add_argument('--max-candidates',type=int,default=24)
 inspect.add_argument('--ocr',action='store_true',help='Use local Tesseract for scanned pages')
 account=sub.add_parser('usage');account.add_argument('out')
 compared=sub.add_parser('compare',help='Report disagreement between two completed runs of the same figure')
 compared.add_argument('left');compared.add_argument('right');compared.add_argument('--out')
 compared.add_argument('--value-tolerance',type=float,default=0.05)
 compared.add_argument('--anchor-tolerance-px',type=float,default=6.)
 for name in ('run','batch'):
  p=sub.add_parser(name);p.add_argument('source');p.add_argument('--config',required=True);p.add_argument('--out',required=True)
  p.add_argument('--query',default='Extract all observed PK concentration-versus-time data points')
  p.add_argument('--page',type=int);p.add_argument('--rotate',type=int,choices=[0,90,180,270],default=0)
  p.add_argument('--crop',type=int,nargs=4);p.add_argument('--context-file');p.add_argument('--reference-image')
 duelled=sub.add_parser('duel',help='Run two providers over one figure, have each judge the other, iterate whichever earns it')
 duelled.add_argument('source');duelled.add_argument('--config',required=True,action='append',
   help='Provider config; give it twice')
 duelled.add_argument('--out',required=True)
 duelled.add_argument('--query',default='Extract all observed PK concentration-versus-time data points')
 duelled.add_argument('--page',type=int);duelled.add_argument('--rotate',type=int,choices=[0,90,180,270],default=0)
 duelled.add_argument('--context-file')
 args=parser.parse_args()
 if args.command=='inspect':
  result=inspect_document(args.source,args.out,args.query,max_candidates=args.max_candidates,ocr=args.ocr)
  print(json.dumps({'manifest':str(Path(args.out)/'manifest.json'),'contact_sheet':result.get('contact_sheet_path')}))
 elif args.command=='usage':print(json.dumps(usage_report(args.out),indent=2))
 elif args.command=='compare':
  report=compare(args.left,args.right,args.value_tolerance,args.anchor_tolerance_px)
  if args.out:write_json(args.out,report)
  print(json.dumps({'agrees':report['agrees'],'disagreements':report['disagreements'],
                    'report':args.out or None},indent=2))
 elif args.command=='batch':batch(args)
 elif args.command=='duel':duel_run(args)
 else:run(args)

if __name__=='__main__':main()

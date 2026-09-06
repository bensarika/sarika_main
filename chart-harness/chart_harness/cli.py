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
  INTERPRET_SCHEMA,REVIEW_AXES_SCHEMA,REVIEW_BATCH_SCHEMA,VERSION)
from .provider import ModelConfig,Provider,ReplayProvider,ExchangeProvider,PendingResponse
from .audit import usage_report, export_batch
from .calibration import recheck_packet
from . import axis_detect
from .consensus import compare
from .coordinate_grid import coordinate_grid
from .visual_check import VisualCheckProvider
from .review_validation import enforce_marker_centers
from . import review_batches

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
   if visual.exists() and hashlib.sha256(visual.read_bytes()).hexdigest()==check.get('image_sha256'):return saved
   # Re-render via the same provider/cache if the mandatory image was removed or changed.
  began=time.monotonic();value=fn();write_json(p,value)
  state['stages'][name]={'path':str(p),'wall_seconds':time.monotonic()-began}
  write_json(state_path,state);return value
 context=bounded_context(args.context_file,args.query,config.get('context_chars',6000))
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
     check['plot_bbox_clamped_from']=interpretation['plot_bbox']
     check['plot_bbox_source']='measured_axes' if measured else 'clamped_model_box'
     interpretation['plot_bbox']=clamped
     # Seeds read off a differently scaled rendering land outside the measured
     # plot; template matching searches the plot instead of chasing them.
     left,top,right,bottom=clamped
     for series in interpretation.get('series',[]):
      seeds=[s for s in series.get('seeds',[]) if left<=s['x']<=right and top<=s['y']<=bottom]
      if seeds!=series.get('seeds',[]):
       check.setdefault('seeds_dropped_outside_plot',{})[series['id']]=len(series.get('seeds',[]))-len(seeds)
       series['seeds']=seeds
     write_json(out/'interpretation.json',interpretation)
   interpretation['axis_tick_check']=check
   write_json(out/'axis_tick_check.json',check)
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
  for batch in batches:
   crop_path=review_batches.crop(out/'working.png',batch,out/'review_batches')
   with Image.open(crop_path) as im:crop_size=im.size
   parts.append(stage(f"review_batch_{batch['index']:03d}",
     lambda batch=batch,crop_path=crop_path,crop_size=crop_size:reviewer.complete(
       f"review_batch_{batch['index']:03d}",
       review_batch_prompt(batch,labels,crop_size,context),
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
  page_transform=orient(native,out/'oriented_page.png',args.rotate)
  with Image.open(out/'oriented_page.png') as im:w,h=im.size
  preview=crop_image(out/'oriented_page.png',[0,0,w,h],out/'layout_view.png',max_side=2200)
  with Image.open(out/'layout_view.png') as im:pw,ph=im.size
  context=bounded_context(args.context_file,args.query,config.get('context_chars',6000))
  layout=locator.complete('layout',f'''Identify distinct requested PK panels in this page ({pw}x{ph} pixels).
Request: {args.query}
Return JSON {{"panels":[{{"id":"iv","label":"IV","crop_bbox":[left,top,right,bottom]}}],
"legend_bbox":[left,top,right,bottom],"notes":[]}}.
Boxes use the supplied image. Panel crops must include axis ticks/units but exclude
neighboring plot interiors. A shared legend is cropped separately. If there is
only one panel return one. Maximum {config.get('max_panels',4)} panels. Never
include predicted/simulated panels when the request is observed measurements.
Return an empty panels list if the requested figure is absent. Source evidence:
{context}''',images=[out/'layout_view.png'])
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
  write_json(out/'layout.json',{'source':str(source),'page':page,'rotation':args.rotate,'layout':layout,'preview_transform':preview})
  results=[];used=set()
  for panel in layout['panels']:
   pid=panel.get('id')
   if not isinstance(pid,str) or not pid.replace('_','').replace('-','').isalnum() or pid in used:raise ValueError('unsafe or duplicate panel ID')
   used.add(pid)
   sub=argparse.Namespace(source=str(out/'oriented_page.png'),config=args.config,out=str(out/'panels'/pid),
      query=args.query+'; panel: '+str(panel.get('label',pid)),page=None,rotate=0,
      crop=native_box(panel['crop_bbox']),context_file=args.context_file,reference_image=None,
      reference_images=([str(ref)] if ref else [])+[str(out/'layout_view.png')])
   r=run(sub)
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
 else:run(args)

if __name__=='__main__':main()

"""CLI and restartable state machine; model responses are never executable."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

import numpy as np
from PIL import Image
from .ingest import inspect_document, render_page, crop_image
from . import geometry
from .prompts import (interpret_prompt,review_axes_prompt,review_batch_prompt,
  cross_judge_prompt,CROSS_JUDGE_SCHEMA,
  INTERPRET_SCHEMA,REVIEW_AXES_SCHEMA,REVIEW_BATCH_SCHEMA,VERSION)
from .provider import ModelConfig,Provider,ReplayProvider,ExchangeProvider,PendingResponse,measures
from .audit import usage_report, export_batch
from .calibration import recheck_packet
from . import axis_detect
from . import detectors
from . import figure_tools
from . import doc_context
from . import gaps
from . import duel
from . import frame_fit
from . import reading_fit
from . import unsteered
from . import coverage
from . import box_check
from .consensus import compare
from .coordinate_grid import coordinate_grid
from .visual_check import VisualCheckProvider
from .review_validation import CENTER_FRACTION_OF_MARK,enforce_marker_centers
from . import review_batches
from . import markers
from . import marker_screen
from . import on_line
from . import progress

def write_json(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(data,indent=2,allow_nan=False));tmp.replace(path)

def make_provider(config,out,role,not_after=None):
 # A call that would return after the run's clock runs out cannot help the run,
 # so the moment the budget expires travels with the provider itself rather than
 # being checked only between stages.
 inner=_make_provider(config,out,role)
 if not_after is not None and hasattr(inner,'not_after'):inner.not_after=not_after
 return VisualCheckProvider(inner,out/"visual_checks"/role,
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

def with_reasoning_effort(config,effort):
 """The same reader, asked to think for a different length of time."""
 copy=json.loads(json.dumps(config))
 copy.setdefault('model',{})['reasoning_effort']=effort
 for role in ('model','reviewer'):
  if isinstance(copy.get(role),dict):copy[role]['reasoning_effort']=effort
 return copy

def race_readings(efforts,readers,read,size,label):
 """Ask the same reader at several thinking depths at once and keep the deepest sound one.

 A deep reading of a plate scan can take minutes, and until it lands nobody can
 tell a slow call from a wrong one. Asking the quick and the deep version
 together costs one extra call and buys a reading to look at within seconds:
 the quick one is reported the moment it arrives, and the deepest reading that
 survives validation is the one the run is built on. Where they disagree about
 how many series are on the page, that disagreement is reported rather than
 resolved here — the pixels settle it downstream.
 """
 readings,failures={},{}
 # A second opinion is worth about as long as the reading it would second-guess:
 # once one depth has answered, the others are given that same span again and
 # then the run moves on, so a reader that thinks for minutes spends its own time
 # rather than the review stages'.
 started=time.monotonic();patience=None
 pool=ThreadPoolExecutor(max_workers=len(efforts))
 try:
  pending={pool.submit(progress.bound(read),effort,readers[effort]):effort for effort in efforts}
  waiting=set(pending)
  while waiting:
   left=None if patience is None else max(0.,patience-(time.monotonic()-started))
   try:
    done=next(as_completed(waiting,timeout=left))
   except TimeoutError:
    progress.say('the {e}-reasoning reading is still out after {s:.0f}s, longer than the '
      'reading it would second-guess took; going on with what is in hand'.format(
        e=', '.join(pending[f] for f in waiting),s=time.monotonic()-started),source=label)
    break
   waiting.discard(done)
   effort=pending[done]
   try:
    reading=done.result()
    validate_interpretation(reading,size)
   except Exception as error:
    failures[effort]=str(error)
    progress.say(f'the {effort}-reasoning reading came back unusable: {error}',source=label)
    continue
   readings[effort]=reading
   if patience is None:patience=2*(time.monotonic()-started)
   progress.say('{e}-reasoning reading is in: {n} series ({names})'.format(e=effort,
     n=len(reading.get('series',[])),
     names=', '.join(str(s.get('label',s['id'])) for s in reading.get('series',[])[:6]) or 'none named'),
     source=label)
 finally:
  pool.shutdown(wait=False,cancel_futures=True)
 if not readings:
  # Every reading came back unusable. The page is still a page: the run goes on
  # without a reading, on what the finders can measure in the pixels, and says
  # plainly that no reader stood behind it.
  progress.say('no reading survived validation ({f}); going on without one, on the '
    'marks the pixels themselves support'.format(
      f='; '.join(f'{e}: {m}' for e,m in failures.items())),source=label)
  return {'unsupported':True,'reason':'no reading survived validation: '+json.dumps(failures),
          'reading_failures':failures,'series':[]}
 counts={e:len(r.get('series',[])) for e,r in readings.items()}
 if len(set(counts.values()))>1:
  progress.say('the depths disagree on how many series are on the page ('
    +', '.join(f'{e}: {n}' for e,n in counts.items())+'); keeping the deepest and '
    'letting the pixel screen settle it',source=label)
 # efforts are listed shallowest-first, so the last one still standing is the
 # deepest. A reading that names no series ends the run with nothing, so a
 # reading that did find series is preferred over a deeper one that gave up.
 standing=[e for e in efforts if e in readings]
 named=[e for e in standing if readings[e].get('series')]
 if named and len(named)<len(standing):
  progress.say('the {g}-reasoning reading gave up on the page while the {k}-reasoning one '
    'named series; building on the reading that found something'.format(
      g=', '.join(e for e in standing if e not in named),k=named[-1]),source=label)
 kept=(named or standing)[-1]
 progress.say(f'building the run on the {kept}-reasoning reading',source=label)
 out=dict(readings[kept])
 out['reasoning_effort']=kept
 out['other_readings']={e:{'series':counts[e]} for e in readings if e!=kept}
 return out

def validate_interpretation(d,size):
 if not isinstance(d,dict):raise ValueError('interpretation must be an object')
 if d.get('unsupported'):return
 w,h=size
 box=d.get('plot_bbox')
 if not isinstance(box,list) or len(box)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in box):
  raise ValueError('plot_bbox needs four finite numbers')
 # A reader that puts the plot's edge a little past the paper has still read the
 # plot. The box is held to the image it describes, and only one that keeps no
 # area inside it is refused; the ticks measured downstream settle where the
 # frame really is.
 held=[min(max(box[0],0),w),min(max(box[1],0),h),min(max(box[2],0),w),min(max(box[3],0),h)]
 if not(held[0]<held[2] and held[1]<held[3]):raise ValueError('plot_bbox keeps no area inside the image')
 if held!=[float(v) for v in box]:
  progress.say('the reader put the plot frame past the page edge ({b}); held it to the image'.format(
    b=','.join(str(round(v)) for v in box)))
  d['plot_bbox']=held
 ids=set()
 for s in d.get('series',[]):
  if not isinstance(s.get('id'),str) or s['id'] in ids:raise ValueError('series IDs must be unique strings')
  ids.add(s['id'])
  if len(s.get('seeds',[]))>1000:raise ValueError('too many model seeds')
  for p in s.get('seeds',[]):
   if not all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) for k in ('x','y')):raise ValueError('nonfinite seed')
  # A seed is only a place to look. One that falls off the page is dropped, and
  # the rest of the reading stands; nothing is invented to replace it.
  inside=[p for p in s.get('seeds',[]) if 0<=p['x']<w and 0<=p['y']<h]
  if 'seeds' in s and len(inside)!=len(s['seeds']):
   progress.say('{n} of the {t} places {sid} pointed at fall off the page; dropped them'.format(
     n=len(s['seeds'])-len(inside),t=len(s['seeds']),sid=s['id']))
   s['seeds']=inside
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
 # A per-call timeout bounds one exchange; a figure costs a dozen of them, so the
 # wall clock is bounded here as well. When it is spent the harness stops asking
 # for more opinions and finalizes what the pixels already support: unreviewed
 # candidates keep no decision and the run cannot be reported as accepted.
 budget=config.get('run_budget_s',300)
 skipped=[]
 expires=start+budget if budget is not None else None
 def over_budget():return budget is not None and time.monotonic()-start>=budget
 def unless_out_of_time(name,fn,default):
  if over_budget():
   skipped.append(name)
   progress.emit('stage',stage=name,state='skipped',reason='run time budget spent')
   return default
  try:
   return stage(name,fn)
  except Exception as error:
   # A call cut off by the run's own clock is time running out, not the figure
   # being unreadable: the stage is recorded as unfinished and everything the
   # pixels already supported is kept rather than thrown away with the run.
   if not over_budget():raise
   skipped.append(name)
   progress.emit('stage',stage=name,state='skipped',
     reason='the run clock ran out during the call: '+str(error))
   progress.say('the clock ran out during {n}; keeping what the pixels already '
     'supported and marking the rest unreviewed'.format(n=name))
   return default
 state_lock=threading.Lock()
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
  progress.emit('stage',stage=name,state='finished',seconds=round(time.monotonic()-began,1),path=str(p))
  with state_lock:
   state['stages'][name]={'path':str(p),'wall_seconds':time.monotonic()-began}
   write_json(state_path,state)
  return value
 context=source_context(args,config,source)
 try:
  page=args.page;rotation=args.rotate
  if source.suffix.lower()=='.pdf':
   if not page:
    manifest=stage('document',lambda:inspect_document(source,out/'document',args.query,
                        max_candidates=config.get('max_candidate_pages',24),ocr=config.get('ocr',False)))
    contact=manifest.get('contact_sheet_path')
    selector=make_provider(config,out,'locator',expires)
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
  # Everything downstream is stated in these pixels, so the viewer is shown the
  # very image the readers are given, not the file as uploaded.
  progress.emit('image',path=str(out/'working.png'),width=size[0],height=size[1],
    page=page,rotation=rotation)
  interpreter=make_provider(config,out,'model',expires)
  # The unaided lane starts with everything else and is never waited on: it is a
  # control, so it costs the reading nothing and settles what the scaffolding is
  # worth on this page rather than in the abstract.
  unaided_pool=unaided_call=None
  if config.get('unsteered_lane',True):
   unaided_pool=ThreadPoolExecutor(max_workers=1)
   # A control whose answer is thrown away for failing the annotation stage is
   # not a control, so its check is recorded rather than enforced.
   unaided_reader=make_provider({**config,'visual_check_strict':False},
     out/'unsteered','model',expires)
   unaided_call=unaided_pool.submit(progress.bound(
     lambda:unsteered.ask(unaided_reader,out/'working.png')))
  references=[Path(p) for p in (getattr(args,'reference_images',[]) or ([args.reference_image] if getattr(args,'reference_image',None) else []))]
  if config.get('coordinate_grid',False):
   references.insert(0,coordinate_grid(out/'working.png',out/'coordinate_grid.png'))
   context += '\nThe blue reference grid uses the exact same pixel dimensions as image 1. Every intersection label is x,y in image 1 pixels. Use it to locate ticks and markers; do not estimate coordinates from a resized display. Read marker bodies in the original unannotated image. Grid lines are not chart data.'
  early=None
  if config.get('detect_ticks',True):
   # Something python measured is on the canvas seconds after the upload, so the
   # wait for the first reader is a wait with the page's own geometry on screen.
   early=axis_detect.detect_ticks(out/'working.png')
   early_box=axis_detect.plot_bbox_from_ticks(early)
   # The box is drawn from the printed rules and ticks, so it can be judged the
   # same way: the ink either continues past its edges or it does not. The
   # verdict travels with the box rather than the watcher having to eyeball it.
   held=box_check.score(out/'working.png',early_box) if early_box else None
   progress.emit('axes',plot_bbox=early_box,
     x_ticks=early.get('x_tick_pixels',[]),y_ticks=early.get('y_tick_pixels',[]),
     measured_only=True,box=held)
   progress.say('measured the printed ticks off the page first: {x} across, {y} up. '
     'Asking the reader what they mean.'.format(x=len(early.get('x_tick_pixels',[])),
                                                y=len(early.get('y_tick_pixels',[]))))
   if held and not held['holds']:
    progress.say('the measured plot box has printed ink running across its {s} side(s), '
      'so whatever falls outside it is not being read'.format(
        s='/'.join(held['edges_cutting_ink'])))
  # The finders need no reader: they measure ink. Running them while the first
  # interpret call is still open puts real marks on the canvas within seconds of
  # the upload instead of after the slowest model call of the run, and the work
  # is not repeated later when the reader's plot box agrees with the measured one.
  early_bank={}
  def look_before_asking():
   try:
    box=axis_detect.plot_bbox_from_ticks(early)
    if not box:return
    found=detectors.run_all(out/'working.png',box,outdir=out/'legend'/'mined',
      methods=config.get('detection_methods'))
    early_bank['plot_bbox'],early_bank['bank']=box,found
    pooled=found['pooled']
    progress.emit('detected_marks',count=len(pooled),counts_by_method=found['counts'],
      corroborated=found['corroborated'],measured_only=True,plot_bbox=box,
      marks=[{k:m[k] for k in ('x','y','found_by','method_count','width')} for m in pooled[:400]],
      reason='located by the finders on the measured plot box, before any reader answered')
    progress.say('the finders located {n} mark-shaped bodies on the page ({m}) while the '
      'reader is still thinking; {c} of them were found by more than one method'.format(
        n=len(pooled),c=found['corroborated'],
        m=', '.join(f'{k}: {v}' for k,v in sorted(found['counts'].items()))))
   except Exception as error:
    # An early look is a courtesy to the watcher; the run does not depend on it.
    progress.say('the early look at the ink did not come off: '+str(error))
  looker=None
  if config.get('detect_ticks',True) and config.get('detect_marks_without_legend',True):
   looker=threading.Thread(target=progress.bound(look_before_asking),daemon=True)
   looker.start()
  # A reader can only be handed the measurements if its endpoint carries
  # questions back; where it cannot, it is told to answer from the image alone
  # rather than being promised tools it will never reach.
  measuring=bool(config.get('measuring_tools',True)) and measures(interpreter)
  interpret_text=interpret_prompt(*size,context,args.query,measuring=measuring)+'\nAdditional images, if any, show legend/source context. All coordinates and template boxes MUST refer to image 1.'
  def measurer(templates=None,asked=None):
   """Python's measurements of this page, for a reader that stops to ask.

   Built per call: the finders run alongside the first reading, so a reader that
   asks late is answered with more of the page than one that asked early, and
   neither waits on the other.
   """
   if not measuring or (asked is not None and not measures(asked)):return None
   return figure_tools.FigureTools(out/'working.png',
     plot_bbox=early_bank.get('plot_bbox'),templates=templates,
     detected_marks=(early_bank.get('bank') or {}).get('pooled') or (),
     ticks=early if config.get('detect_ticks',True) else None)
  def read_figure(effort=None,provider=None):
   asked=provider or interpreter
   tools=measurer(asked=asked)
   reading=asked.complete('interpret',interpret_text,
     images=[out/'working.png']+references,schema=INTERPRET_SCHEMA,
     tools=tools.schemas() if tools else None,tool_runner=tools)
   if tools and tools.calls:
    progress.say('stopped to have python measure the page {n} times before answering '
      '({m})'.format(n=len(tools.calls),
        m=', '.join(sorted({str(c['name']) for c in tools.calls}))),
      source=provider_label(config))
    progress.emit('measurements_asked_for',calls=tools.calls[:60],
      count=len(tools.calls),stage='interpret')
    write_json(out/'measurements_asked_for_interpret.json',tools.calls)
   return reading
  efforts=[e for e in (config.get('interpret_reasoning_efforts') or []) if e]
  if len(efforts)>1:
   readers={e:make_provider(with_reasoning_effort(config,e),out/('interpret_'+e),'model',expires) for e in efforts}
   interpretation=stage('interpretation',lambda:race_readings(
     efforts,readers,read_figure,size,provider_label(config)))
  else:
   interpretation=stage('interpretation',lambda:read_figure())
  try:
   validate_interpretation(interpretation,size)
  except Exception as error:
   # An unusable reading loses the reading, not the page: the run carries on on
   # the pixels and records what the reader got wrong.
   progress.say('the reading came back unusable ({e}); going on without it, on the '
     'marks the pixels themselves support'.format(e=error),source=provider_label(config))
   interpretation={'unsupported':True,'reason':'reading failed validation: '+str(error),
                   'series':[]}
  interpretation['overlay_label']=provider_label(config)
  # What the reader says it sees, in its own words, so a watcher can tell a slow
  # call from a wrong reading before any coordinate is proposed.
  progress.say('reads this as {n} series: {names}'.format(
    n=len(interpretation.get('series',[])),
    names=', '.join(str(s.get('label',s['id'])) for s in interpretation.get('series',[])[:6]) or 'none named'),
    source=provider_label(config))
  for note in (interpretation.get('notes') or [])[:3]:progress.say(note,source=provider_label(config))
  for region in (interpretation.get('unresolved_regions') or [])[:3]:
   progress.say('says one area cannot be resolved: '+str(region.get('reason',region)),source=provider_label(config))
  progress.emit('legend',plot_bbox=interpretation.get('plot_bbox'),
    series=[{k:s.get(k) for k in ('id','label','marker','marker_description','colour')}
            for s in interpretation.get('series',[])],
    sample_times=interpretation.get('sample_times'),
    unresolved_regions=interpretation.get('unresolved_regions',[]),
    image=str(out/'working.png'))
  if not interpretation.get('unsupported') and config.get('detect_ticks',True):
   # No tolerance is stated: each axis is judged against the spacing of its own
   # printed ticks, so the same rule holds for a thumbnail and a plate scan.
   tick_tolerance=config.get('axis_tick_tolerance_px')
   check=axis_detect.crosscheck(out/'working.png',interpretation,tick_tolerance)
   if not check['agrees'] and not check['inconclusive'] and config.get('repair_axes_from_ticks',True):
    prompt,tick_images=axis_detect.repair_packet(out/'working.png',check['detected'],out/'tick_repair')
    repaired=unless_out_of_time('axis_repair',
      lambda:interpreter.complete('axis_repair',prompt,images=tick_images+references),
      {'status':'unread','reason':'run time budget spent'})
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
   progress.say('measured {x} x-ticks and {y} y-ticks; the reader\'s calibration {verdict}'.format(
     x=len(check['detected'].get('x_tick_pixels',[])),y=len(check['detected'].get('y_tick_pixels',[])),
     verdict='could not be checked against them' if check.get('inconclusive')
             else ('agrees with them' if check.get('agrees') else 'disagrees with them')))
   progress.emit('axes',plot_bbox=interpretation.get('plot_bbox'),
     x_ticks=check['detected'].get('x_tick_pixels',[]),y_ticks=check['detected'].get('y_tick_pixels',[]),
     agrees=check.get('agrees'),inconclusive=check.get('inconclusive'),
     x_axis=interpretation.get('x_axis'),y_axis=interpretation.get('y_axis'))
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
    progress.say('cut {n} marker glyph(s) out of the legend to search the plot for'.format(n=len(glyphs)))
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
  # A reader declining the page is an opinion about the page, not the end of it.
  # The ink is still printed, so the finders measure it and every mark they can
  # stand behind is reported in pixels, carrying the reader's objection with it,
  # for a person to attribute rather than for the run to abandon.
  if interpretation.get('unsupported'):
   if looker is not None:looker.join()
   box=early_bank.get('plot_bbox') or [0,0,size[0],size[1]]
   bank=early_bank.get('bank') or detectors.run_all(out/'working.png',box,
     outdir=out/'legend'/'mined',methods=config.get('detection_methods'))
   pooled=bank['pooled']
   # More than one finder standing behind a mark is the strongest thing the page
   # can say on its own; only where nothing is corroborated does a single finder
   # carry a mark, and the reading says which held it up.
   held=[m for m in pooled if m.get('method_count',1)>1] or pooled
   reason=interpretation.get('reason') or 'the reader gave no reason'
   progress.say('the reader declined this page ({r}); going on with the {n} mark(s) '
     'the finders can stand behind, in pixels, for a person to attribute'.format(
       r=reason,n=len(held)))
   progress.emit('detected_marks',count=len(held),counts_by_method=bank['counts'],
     corroborated=bank['corroborated'],plot_bbox=box,
     marks=[{k:m[k] for k in ('x','y','found_by','method_count','width')} for m in held[:400]],
     reason='reader declined the page; marks located by the finders alone')
   points=[{'candidate_id':'mark_%03d'%i,'series':None,'series_label':None,
            'x':None,'y':None,'pixel_x':m['x'],'pixel_y':m['y'],
            'found_by':m['found_by'],'method_count':m.get('method_count',1),
            'role':'unattributed'} for i,m in enumerate(held)]
   progress.emit('candidates',count=len(points),candidates=points,
     reason='located on the pixels without a reading; no axis values available')
   result={'status':'review_required','reason':reason,'points':points,
     'counts':{'observed':0,'unattributed':len(points)},
     'plot_bbox':box,'detected_marks':{'count':len(pooled),'held':len(held),
       'counts_by_method':bank['counts'],'corroborated':bank['corroborated']},
     'diagnostics':[{'code':'reader_declined_the_page','reason':reason,
       'carried_on':'marks measured on the pixels, reported without axis values'}],
     'time_budget':{'seconds':budget,'spent':round(time.monotonic()-start,1),
                    'stages_skipped':skipped}}
   write_json(out/'result.json',result);return result
  # No legend column, or a legend of words only. The marks are still printed and
  # they are thicker than every line on the sheet, so Python measures where they
  # are before anything is proposed: a reader whose coordinates land on white
  # paper cannot then be confirmed by mining around those same coordinates. The
  # marks seed every series, so which group each belongs to stays an open question
  # for the reviewer instead of being decided by the detector.
  # Several independent finders run at once - ink thickness, printed colour, a
  # shape pass over the whole plot, bar tops, and following the curves - because
  # no one of them reads every figure. Their hits are pooled and a location more
  # than one of them found is recorded as corroborated.
  bank=None
  if (config.get('detect_marks_without_legend',True)
      and not any(s.get('template_bbox') for s in interpretation['series'])):
   if looker is not None:looker.join()
   same_frame=early_bank.get('plot_bbox')==[float(v) for v in interpretation['plot_bbox']]
   bank=early_bank['bank'] if same_frame else detectors.run_all(out/'working.png',
     interpretation['plot_bbox'],outdir=out/'legend'/'mined',
     methods=config.get('detection_methods'))
   found=bank['methods'].get('thickness',{}).get('marks') or []
   pooled=bank['pooled']
   if pooled:
    lone=min((m for m in found if not m['crowded']),key=lambda m:m['width']*m['height'],default=None)
    write_json(out/'detected_marks.json',{'source':'detector_bank','count':len(pooled),
      'counts_by_method':bank['counts'],'corroborated':bank['corroborated'],
      'corroboration_radius_px':bank['corroboration_radius_px'],
      'marks_suggested':sum(m['marks_suggested'] for m in found),
      'marks':found,'pooled':pooled})
    for series in interpretation['series']:
     series['marker']='blob'
     series['seeds']=[{'x':m['x'],'y':m['y'],'found_by':m['found_by']} for m in pooled]
     if lone:
      series['template_bbox']=lone['bbox']
      series['legend_glyph']={'template_path':None,'width':lone['width'],'height':lone['height'],
                              'ink_fraction':None,'mined_from_plot':True}
    write_json(out/'interpretation.json',interpretation)
    progress.emit('detected_marks',count=len(pooled),counts_by_method=bank['counts'],
      corroborated=bank['corroborated'],
      marks_suggested=sum(m['marks_suggested'] for m in found),
      crowded=sum(1 for m in found if m['crowded']),
      marks=[{k:m[k] for k in ('x','y','found_by','method_count','width')} for m in pooled[:400]],
      plot_bbox=interpretation['plot_bbox'],
      reason='no legend glyphs; marks located by several independent finders, '
             'group attribution left open')
   else:
    progress.emit('detected_marks',count=0,counts_by_method=bank['counts'],
      marks_suggested=0,crowded=0,corroborated=0,
      reason='no legend glyphs and no finder located a mark-shaped body in the plot')
  # A reader answers in the pixel space it was shown, and an endpoint that
  # shrinks a big scan before the model sees it hands back a reading that starts
  # at the plot's corner and then falls short of it - every point high, nothing
  # reaching the right-hand edge. Measured against the marks python found, that
  # is one stretch of the frame rather than dozens of separate misses, so the
  # reading is registered onto them before anything is refined.
  if config.get('register_reading_to_marks',True):
   marks_for_fit=(early_bank.get('bank') or bank or {}).get('pooled') or []
   seeds=[(s['id'],i,seed) for s in interpretation.get('series',[])
          for i,seed in enumerate(s.get('seeds',[]) or [])
          if isinstance(seed,dict) and 'x' in seed and 'y' in seed]
   glyphs=[max(float(s['template_bbox'][2])-float(s['template_bbox'][0]),
               float(s['template_bbox'][3])-float(s['template_bbox'][1]))
           for s in interpretation.get('series',[]) if s.get('template_bbox')]
   widths=[m.get('width') for m in marks_for_fit if m.get('width')]
   reach=(statistics.median(glyphs) if glyphs else
          statistics.median(widths) if widths else None)
   frame=reading_fit.register([(s[2]['x'],s[2]['y']) for s in seeds],
     [(m['x'],m['y']) for m in marks_for_fit],reach,
     bounds=interpretation.get('plot_bbox')) if seeds and reach else None
   if frame:
    for _,_,seed in seeds:
     was={'x':seed['x'],'y':seed['y']}
     seed['x'],seed['y']=reading_fit.carry(frame,seed['x'],seed['y'])
     seed['moved_into_the_measured_frame']=was
    write_json(out/'reading_frame.json',frame)
    write_json(out/'interpretation.json',interpretation)
    progress.say('the reading was drawn in a different frame from the page: '
      'stretched onto the measured marks, it lands on {n} of them where it '
      'landed on {b}'.format(n=frame['landed_on_marks'],b=frame['landed_before']))
    progress.emit('reading_frame',**frame)
  proposals=stage('proposals',lambda:geometry.analyze(out/'working.png',interpretation,out/'geometry'))
  # A candidate is only searched for beside a seed the reader gave, so a reading
  # that lists the first few sampling columns and stops leaves the rest of the
  # plot unexamined however well its own points sit on their marks. Python has
  # already measured mark-shaped bodies right across the box, and one standing in
  # a column no candidate occupies is a place nobody looked: that one is carried
  # in with its group left open, and faces the same pixel screen as the rest. A
  # body inside a column the reading did read is left alone, because the finders
  # also catch error-bar caps and crossing ink and filling in from those would
  # trade a short reading for an inflated one.
  if config.get('cover_measured_marks',True) and proposals.get('candidates') is not None:
   box=proposals.get('plot_bbox')
   # Marks and candidates have to have been measured on the same plot box, or the
   # comparison is between two different frames.
   same=bank if bank is not None else (early_bank.get('bank')
     if box and early_bank.get('plot_bbox')==[float(v) for v in box] else None)
   measured=[m for m in (same or {}).get('pooled') or [] if coverage.inside(m,box)]
   near=coverage.reach(measured,interpretation.get('series'))
   spanned=coverage.span(measured,proposals['candidates'],box)
   added=coverage.add(proposals,measured,near,
     [s['id'] for s in interpretation.get('series',[])]) if measured else []
   if added:
    geometry.redraw(out/'working.png',proposals,provider_label(config))
   if measured:
    progress.say(coverage.sentence(added,spanned))
    progress.emit('coverage',added=len(added),measured_marks=len(measured),
      within_px=near,**(spanned or {}))
  # A proposal is only meaningful as a reading of the figure, so it is reported in
  # the figure's own units and against the group it was attributed to; the pixels
  # stay alongside because they are what the screen re-measures.
  axes={};loose=[]
  for name in ('x_axis','y_axis'):
   try:
    axes[name]=geometry.Axis(interpretation.get(name),name)
    loose+=axes[name].loose_fits
   except Exception:axes[name]=None
  for complaint in loose:progress.say('the printed ticks do not sit on one line: '+complaint)
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
  progress.say('{n} candidate point(s) proposed; each is now re-measured against the '
    'source pixels before it can be exported'.format(n=len(proposals['candidates'])))
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
  reviewer=make_provider(config,out,'reviewer',expires)
  # Review is split so no single call carries the whole figure: calibration once,
  # then a few candidates per crop of the original pixels, each call bounded.
  labels=[s['label'] for s in interpretation['series']]
  detected=(interpretation.get('axis_tick_check') or {}).get('detected') or {}
  axes_review=unless_out_of_time('review_axes',
    lambda:reviewer.complete('review_axes',
       review_axes_prompt(labels,context,detected),images=[out/'working.png']+references,
       schema=REVIEW_AXES_SCHEMA),
    {'status':'unread','reason':'run time budget spent','missing_points':[]})
  if detected and isinstance(axes_review.get('axis_check'),dict):
   axis_check,dropped=axis_detect.resolve_tick_indices(axes_review['axis_check'],detected,
     config.get('axis_tick_tolerance_px'))
   axes_review={**axes_review,'axis_check':axis_check}
   if dropped:axes_review['notes']=list(axes_review.get('notes',[]))+[
     f'review anchors ignored, they name no measured tick: {json.dumps(dropped)}']
   write_json(out/'review_axes_resolved.json',axes_review)
  batches=review_batches.plan(proposals['candidates'],size,
    batch_size=config.get('review_batch_size',review_batches.BATCH_SIZE),
    padding_px=config.get('review_batch_padding_px',review_batches.PADDING_PX),
    min_side=config.get('review_batch_min_side_px',review_batches.MIN_SIDE))
  write_json(out/'review_batches.json',batches)
  jobs=[]
  gray=markers.load_gray(out/'working.png') if config.get('screen_candidates_against_legend',True) else None
  templates={s['id']:s['template_bbox'] for s in interpretation['series'] if s.get('template_bbox')}
  by_candidate={c['candidate_id']:c for c in proposals['candidates']}
  for batch in batches:
   crop_path=review_batches.crop(out/'working.png',batch,out/'review_batches')
   with Image.open(crop_path) as im:crop_size=im.size
   measurements=marker_screen.batch_feedback(gray,templates,batch,by_candidate) if gray is not None else None
   def judge_one(batch=batch,crop_path=crop_path,crop_size=crop_size,measurements=measurements):
    # The judge measures the same pixels the screen will hold it to, on the whole
    # page, so a crop's edge cannot hide the mark it is deciding about.
    tools=measurer(templates,reviewer)
    answer=reviewer.complete(f"review_batch_{batch['index']:03d}",
      review_batch_prompt(batch,labels,crop_size,context,measurements,
        config.get('judging_provider_label'),measuring=bool(tools)),
      images=[crop_path],schema=REVIEW_BATCH_SCHEMA,
      tools=tools.schemas() if tools else None,tool_runner=tools)
    if tools and tools.calls:
     write_json(out/'review_batches'/f"measurements_{batch['index']:03d}.json",tools.calls)
     progress.emit('measurements_asked_for',calls=tools.calls[:60],
       count=len(tools.calls),stage=f"review_batch_{batch['index']:03d}")
    return answer
   jobs.append((f"review_batch_{batch['index']:03d}",judge_one))
  # The crops are independent of one another, so the wall clock buys as many of
  # them as the endpoint will take at once; results stay in batch order.
  missed={'decisions':[],'notes':['batch not reviewed: run time budget spent']}
  workers=max(1,int(config.get('parallel_calls',4)))
  reviewed=[0]
  def review_one(job):
   part=unless_out_of_time(job[0],job[1],missed)
   # Each crop reports as it lands, so the figure fills in during the review
   # rather than all at once when the last call returns.
   reviewed[0]+=1
   decisions=part.get('decisions') or []
   progress.emit('reviewed_batch',done=reviewed[0],of=len(jobs),
     decisions=[{k:d.get(k) for k in ('candidate_id','series_id','role','pixel_x','pixel_y','reason')}
                for d in decisions])
   progress.say('crop {n} of {total} reviewed: {kept} kept, {out} thrown out'.format(
     n=reviewed[0],total=len(jobs),
     kept=sum(1 for d in decisions if d.get('role')=='observed'),
     out=sum(1 for d in decisions if d.get('role') not in ('observed',None))))
   return part
  with ThreadPoolExecutor(max_workers=min(workers,max(1,len(jobs)))) as pool:
   parts=list(pool.map(progress.bound(review_one),jobs))
  review=review_batches.merge(axes_review,parts,batches)
  write_json(out/'review.json',review)
  review=enforce_marker_centers(review,proposals,
    config.get('review_center_fraction_of_mark',CENTER_FRACTION_OF_MARK))
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
   progress.say('pixel screen: {c} checked, {f} failed on the image itself, {m} moved onto '
     'the mark by python'.format(c=len(screens),f=sum(1 for s in screens if not s.get('passed')),
                                 m=sum(1 for s in screens if s.get('corrected'))))
   progress.emit('screen',checked=len(screens),
     failed=sum(1 for s in screens if not s.get('passed')),
     corrected=sum(1 for s in screens if s.get('corrected')),results=screens[:200])
   if any(s.get('corrected') for s in screens):write_json(out/'proposals.json',proposals)
  result=geometry.finalize(out/'working.png',interpretation,proposals,review,out/'final')
  if (config.get('recheck_axes',True) and result.get('axis_agreement') and
      not all(v['accepted'] for v in result['axis_agreement'].values())):
   prompt,tick_images=recheck_packet(out/'working.png',interpretation['plot_bbox'],out/'tick_recheck')
   calibrator=make_provider(config,out,'calibrator',expires)
   checked=unless_out_of_time('calibration_recheck',lambda:calibrator.complete('calibration_recheck',
       prompt,images=tick_images+references),{'status':'unread'})
   if checked.get('status')=='readable' and isinstance(checked.get('axis_check'),dict):
    revised_review={**review,'axis_check':checked['axis_check']}
    first_agreement=result['axis_agreement']
    result=geometry.finalize(out/'working.png',interpretation,proposals,revised_review,out/'final')
    result['initial_axis_agreement']=first_agreement
    result['calibration_recheck_used']=True
  # A series is printed at a rhythm, so the marks it kept say how many it should
  # have: a jump several steps wide is a hole, and the hole's width says how many
  # marks belong in it. The predicted places are only places to look - a mark is
  # added back solely where a finder already located ink - and whatever stays
  # empty is reported as missing rather than passed over.
  if config.get('estimate_missing_from_spacing',True) and result.get('rows'):
   if bank is None:
    bank=detectors.run_all(out/'working.png',interpretation['plot_bbox'],
      methods=config.get('detection_methods'))
   spacing_report=gaps.report(result['rows'],bank['pooled'],
     bank['corroboration_radius_px'] or 0.,
     {s['id']:s.get('label',s['id']) for s in interpretation.get('series',[])})
   result['spacing_check']={'series':spacing_report,
     'missing':sum(e['missing'] for e in spacing_report.values()),
     'recoverable':sum(len(e['recovered']) for e in spacing_report.values()),
     'search_radius_px':bank['corroboration_radius_px'],
     'basis':'median spacing of the accepted marks in each series'}
   if result['spacing_check']['missing']:
    result['status']='review_required'
    result.setdefault('diagnostics',[]).append({'code':'series_shorter_than_its_spacing_implies',
      'missing':result['spacing_check']['missing'],
      'advice':gaps.advice(spacing_report)})
   progress.say(gaps.advice(spacing_report) or 'every series is as long as the spacing of '
     'its own marks implies')
   progress.emit('spacing',missing=result['spacing_check']['missing'],
     recoverable=result['spacing_check']['recoverable'],
     series={k:{'kept':v['kept'],'expected':v['expected'],'missing':v['missing'],
                'step_px':v['step_px'],'label':v['label']} for k,v in spacing_report.items()},
     predicted=[h['predicted'][0] for e in spacing_report.values() for h in e['holes']][:200])
  # A mark is printed on its curve and every curve is sampled, so the page can
  # answer two questions about the kept marks on its own: does each one stand on
  # a drawn stroke, and did any curve come away with nothing? Both are measured
  # against the figure's own pen and mark width, and both hold the run to review
  # rather than adding or moving a point.
  if config.get('check_marks_sit_on_their_curve',True) and result.get('rows'):
   kept=[r for r in result['rows'] if r.get('status')=='observed']
   width=(bank or {}).get('mark_width_px') if bank else None
   curve_report=on_line.check(out/'working.png',interpretation['plot_bbox'],kept,mark_width=width)
   if curve_report.get('available'):
    tolerance=on_line.column_tolerance(kept,width)
    sampling=on_line.columns(kept,tolerance)
    expected=[s['id'] for s in interpretation.get('series',[])]
    holes=on_line.gaps_in_columns(sampling,expected)
    crossed=on_line.crossings(sampling)
    doubled=[{'column':c['column'],'pixel_x':c['pixel_x'],'series':c['doubled']}
             for c in sampling if c['doubled']]
    result['curve_check']={
      'off_curve':curve_report['off_curve'],'points':curve_report['points'],
      'curves':curve_report['curves'],'unsampled_curves':curve_report['unsampled_curves'],
      'tolerance_px':curve_report['tolerance_px'],'stroke_px':curve_report['stroke_px'],
      'basis':curve_report['basis']}
    result['sampling_columns']={
      'tolerance_px':tolerance,
      'columns':[{'column':c['column'],'pixel_x':c['pixel_x'],
                  'series_order':c['series_order'],'doubled':c['doubled']} for c in sampling],
      'series_missing_from_a_column':holes,'crossing_series':crossed,
      'doubled_in_a_column':doubled,
      'basis':'the marks stand in the columns of the sampling times they share'}
    trouble=[]
    if curve_report['off_curve']:trouble.append({'code':'kept_marks_sit_off_every_curve',
      'count':curve_report['off_curve'],
      'candidates':[m['candidate_id'] for m in curve_report['points'] if m.get('on_curve') is False]})
    if curve_report['unsampled_curves']:trouble.append({'code':'a_drawn_curve_carries_no_mark',
      'count':len(curve_report['unsampled_curves']),'curves':curve_report['unsampled_curves'][:12]})
    if doubled:trouble.append({'code':'one_series_twice_at_one_sampling_time','columns':doubled})
    if holes:trouble.append({'code':'series_absent_from_a_column_its_neighbours_appear_in',
      'holes':holes[:40],
      'note':'where no curves cross, the order of the others brackets where to look'})
    if trouble:
     result['status']='review_required'
     result.setdefault('diagnostics',[]).extend(trouble)
    progress.say(on_line.advice(curve_report) or 'every kept mark stands on a drawn curve and '
      'every curve carries marks')
    progress.emit('curve_check',off_curve=curve_report['off_curve'],
      curves=len(curve_report['curves']),
      unsampled=[c['bbox'] for c in curve_report['unsampled_curves']][:20],
      columns=len(sampling),missing_in_columns=len(holes),crossing_series=crossed,
      tolerance_px=curve_report['tolerance_px'])
  # Entire-job completeness is stricter than candidate precision.
  unresolved=interpretation.get('unresolved_regions',[])
  if unresolved or review.get('missing_points') or review.get('status')!='accepted':
   result['status']='review_required'
  result['unresolved_regions']=unresolved
  if loose:
   result['status']='review_required'
   result.setdefault('diagnostics',[]).append({'code':'axis_anchors_do_not_sit_on_one_line','detail':loose})
  if 'axis_tick_check' in interpretation:result['axis_tick_check']=interpretation['axis_tick_check']
  result['model_mode']=config.get('mode',config.get('model',{}).get('mode','api'))
  result['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
  result['wall_seconds_this_invocation']=time.monotonic()-start
  result['time_budget']={'seconds':budget,'spent':round(time.monotonic()-start,1),'stages_skipped':skipped}
  if skipped:
   result['status']='review_required'
   result.setdefault('diagnostics',[]).append({'code':'run_time_budget_spent','stages_skipped':skipped})
  result['notes']=list(result.get('notes',[]))+[
    'Pixel coordinates refer to working.png. image_manifest.json maps them to the source page raster.',
    'Model agreement and overlay fit do not establish original numerical ground truth.',
    'Missing observations are not reconstructed; unresolved regions prevent whole-chart acceptance.']
  checked=unless_out_of_time('final_visual_check',
    lambda:interpreter.check('final_output',result,[out/'working.png']),
    {'_visual_check':{'assessment':'unavailable','reason':'run time budget spent',
                      'image_path':str(out/'working.png')}})
  result['_visual_check']=checked['_visual_check']
  if (result['_visual_check']['assessment']=='concerns' or interpretation.get('_visual_check',{}).get('assessment')=='concerns' or review.get('_visual_check',{}).get('assessment')=='concerns'):result['status']='review_required'
  if unaided_call is not None:
   # Whatever the control has by now: it is collected, never waited on, so a slow
   # unaided call is missing from the comparison rather than late to the reading.
   try:
    unaided=unaided_call.result(timeout=0)
   except TimeoutError:
    unaided=None
    progress.say('the unaided reading is still out when the run ends; nothing to '
      'compare the scaffolding against on this page')
   except Exception as error:
    unaided=None
    progress.say('the unaided reading came back unusable: '+str(error))
   unaided_pool.shutdown(wait=False,cancel_futures=True)
   if unaided is not None:
    against=unsteered.compare(unaided,result.get('rows') or [])
    unsteered.write(out/'unsteered_reading.json',unaided)
    unsteered.write(out/'unsteered_comparison.json',against)
    result['unsteered']={'reading':str(out/'unsteered_reading.json'),**against}
    progress.say(unsteered.summary(unaided))
    progress.say(against['reading'])
    progress.emit('unsteered',**against,series=[
      {'label':s.get('label') or s.get('id'),'points':(s.get('points') or [])[:200]}
      for s in (unaided.get('series') or [])[:20]])
  result['visual_checks']=[str(p) for p in sorted((out/'visual_checks').rglob('*.png'))]
  write_json(out/'result.json',result)
  write_json(result['json_path'],result)
  progress.say('finished as {s}: {counts}'.format(s=result['status'],
    counts=' · '.join(f'{k} {v}' for k,v in (result.get('counts') or {}).items()) or 'no rows'))
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
  shown=[False]
  def read_layout(stage,clockwise):
   """Lay the page out at this rotation; the sheet itself may be printed sideways."""
   transform=orient(native,out/'oriented_page.png',clockwise)
   with Image.open(out/'oriented_page.png') as im:size=im.size
   view=crop_image(out/'oriented_page.png',[0,0,size[0],size[1]],out/'layout_view.png',max_side=2200)
   if not shown[0]:
    # The page goes on screen before anyone is asked about it: the watcher sees
    # what was uploaded, upright, while the panel call is still open.
    shown[0]=True
    progress.emit('image',path=str(out/'oriented_page.png'),width=size[0],height=size[1],
      page=page,rotation=clockwise)
    progress.say('page is up ({w}x{h}px); asking which panels on it were requested'.format(
      w=size[0],h=size[1]))
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
   # A reader's box that runs off the sheet is a reading of the page's edge, not a
   # reason to abandon the page: it is trimmed to the paper and only a box that
   # keeps no area at all is refused.
   trimmed=[min(max(box[0],0),pw),min(max(box[1],0),ph),min(max(box[2],0),pw),min(max(box[3],0),ph)]
   if trimmed!=list(box):
    progress.say('the panel box ran off the sheet ({b}); trimmed it to the page'.format(
      b=','.join(str(round(v)) for v in box)))
   box=trimmed
   if not(0<=box[0]<box[2]<=pw and 0<=box[1]<box[3]<=ph):raise ValueError('panel box keeps no area inside the image')
   a=scale@np.array([box[0],box[1],1]);b=scale@np.array([box[2],box[3],1])
   return [max(0,int(math.floor(a[0]))),max(0,int(math.floor(a[1]))),min(w,int(math.ceil(b[0]))),min(h,int(math.ceil(b[1])))]
  ref=None
  legend=layout.get('legend_bbox')
  # A reader with no legend to point at sometimes answers with an empty box
  # rather than nothing. That is a page without a legend, not a broken page.
  if legend and not(len(legend)==4 and legend[0]<legend[2] and legend[1]<legend[3]):
   progress.say('the reader returned an empty legend box; reading the page as having no legend')
   legend=None
  if legend:
   ref=out/'legend.png';crop_image(out/'oriented_page.png',native_box(legend),ref)
  write_json(out/'layout.json',{'source':str(source),'page':page,'rotation':rotation,'layout':layout,'preview_transform':preview})
  results=[];used=set()
  for panel in layout['panels']:
   pid=panel.get('id')
   if not isinstance(pid,str) or not pid.replace('_','').replace('-','').isalnum() or pid in used:raise ValueError('unsafe or duplicate panel ID')
   used.add(pid)
   # A box marked on a downscaled view lands a few pixels inside the drawing and
   # clips the rule or the last column. Moving one edge off the ink can expose
   # another - freeing the bottom of a curve reveals that its right end was cut
   # too - so the box is scored and moved again until nothing crosses it, rather
   # than once and hoped over.
   panel_box,attempts=box_check.settle(out/'oriented_page.png',native_box(panel['crop_bbox']))
   write_json(out/'panels'/pid/'panel_box.json',{'asked_for':native_box(panel['crop_bbox']),
     'settled_on':panel_box,'attempts':attempts})
   progress.say('panel {p}: {s}'.format(p=pid,s=box_check.sentence(attempts)),
     source=provider_label(config))
   if len(attempts)>1:
    progress.emit('panel_box_widened',panel=pid,code='panel_box_grown_off_the_ink',
      **{'from':attempts[0]['box'],'to':panel_box,'rounds':len(attempts)-1,
         'moved':[attempts[0]['box'][0]-panel_box[0],attempts[0]['box'][1]-panel_box[1],
                  panel_box[2]-attempts[0]['box'][2],panel_box[3]-attempts[0]['box'][3]]})
   sub=argparse.Namespace(source=str(out/'oriented_page.png'),config=args.config,out=str(out/'panels'/pid),
      query=args.query+'; panel: '+str(panel.get('label',pid)),page=None,rotate=0,
      crop=[int(v) for v in panel_box],context_file=args.context_file,reference_image=None,
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
 def judged(pair):
  side,other=pair
  judge=make_provider(other['config'],out/'judges'/other['name'],'reviewer')
  return side,other,cross_judge(judge,side['dir'],side['name'],context)
 # Neither judgment depends on the other, so both are asked at once.
 with ThreadPoolExecutor(max_workers=2) as pool:
  verdicts=list(pool.map(progress.bound(judged),((sides[0],sides[1]),(sides[1],sides[0]))))
 for side,other,judgment in verdicts:
  judgments[side['name']]=judgment
  judgments[side['name']]['judged_by']=other['name']
  reflection=duel.self_reflection(side['dir'])
  side['reflection']=reflection
  decisions[side['name']]=duel.decide(judgments[side['name']],reflection,first)
  progress.say('judging {side}: {verdict}. {worst}'.format(side=side['name'],
    verdict=judgments[side['name']]['verdict'],
    worst=judgments[side['name']].get('worst_problem') or ''),source=other['name'])
  progress.emit('judgment',side=side['name'],judged_by=other['name'],
    verdict=judgments[side['name']]['verdict'],
    worst_problem=judgments[side['name']]['worst_problem'],
    findings=judgments[side['name']]['findings'][:20],
    iterate=decisions[side['name']]['iterate'],
    reasons=decisions[side['name']]['reasons'])
 write_json(out/'cross_judgments.json',judgments)
 write_json(out/'decisions.json',decisions)
 def second_pass(side):
  decision=decisions[side['name']]
  feedback=out/f"feedback_{side['name']}.md"
  feedback.write_text(context+'\n\n'+duel.feedback_text(decision,judgments[side['name']]))
  directory=out/(side['name']+'_pass2')
  progress.say('running a second pass with corrections: '+', '.join(
    r['code'] for r in decision['reasons'])[:300])
  progress.emit('iteration',side=side['name'],state='started',
    feedback=duel.feedback_text(decision,judgments[side['name']]))
  entry={'dir':str(directory),'feedback_path':str(feedback),
         'result':rerun(side,directory,str(feedback))}
  side['dir']=directory
  progress.emit('iteration',side=side['name'],state='finished',
    status=entry['result'].get('status'))
  return side['name'],entry
 again=[s for s in sides if decisions[s['name']]['iterate']]
 if again:
  with ThreadPoolExecutor(max_workers=len(again)) as pool:
   iterations.update(dict(pool.map(progress.bound(second_pass),again)))
 final=panel_comparison(sides[0]['dir'],sides[1]['dir']) if iterations else first
 report=duel.report({s['name']:{'dir':str(s['dir']),'reflection':s['reflection']} for s in sides},
   first,judgments,decisions,iterations,final)
 write_json(out/'duel_report.json',report)
 progress.emit('duel_report',agrees=report['agrees'],iterated=sorted(iterations),
   path=str(out/'duel_report.json'))
 return report

def duel_run(args):
 """Both readers over one figure at the same time, then adjudication."""
 out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 source=Path(args.source).resolve()
 sides=duel_sides(args.config)
 def batch_args(side,directory,context_file=None):
  return argparse.Namespace(source=str(source),config=side['config_path'],out=str(directory),
    query=args.query,page=args.page,rotate=args.rotate,crop=None,
    context_file=context_file,reference_image=None,reference_images=[])
 # The readings are independent, and each is bounded by its own run budget, so
 # the duel costs about one reading's wall clock rather than two.
 def read(side):
  side['dir']=out/side['name']
  side['result']=batch(batch_args(side,side['dir']))
  return side
 with ThreadPoolExecutor(max_workers=len(sides)) as pool:
  sides=list(pool.map(progress.bound(read),sides))
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

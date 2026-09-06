"""Mandatory same-provider annotation stage; source pixels and anchors are fixed."""
import hashlib,json,math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

class VisualCheckError(ValueError):pass

def anchors_for(result):
 anchors=[]
 for p in result.get("rows",[]):
  anchors.append({"id":p["candidate_id"],"x":p["pixel_x"],"y":p["pixel_y"]})
 for series in result.get('series',[]):
  for i,p in enumerate(series.get('seeds',[])):
   anchors.append({'id':f"{series['id']}:{i+1}",'x':p['x'],'y':p['y']})
 for p in result.get('candidates',[]):
  anchors.append({'id':p['candidate_id'],'x':p['pixel']['x'],'y':p['pixel']['y']})
 return anchors

def render(source,points,annotations,path,title):
 im=Image.open(source).convert('RGB');w,h=im.size
 # A separate label column keeps chart text and annotation text from colliding.
 scale=min(1,1400/max(w,h));display=im.resize((round(w*scale),round(h*scale)))
 row_height=58;header=88;side=600
 canvas=Image.new('RGB',(display.width+side,max(display.height+header,len(annotations)*row_height+header+40)),'white')
 canvas.paste(display,(0,header));draw=ImageDraw.Draw(canvas);font=ImageFont.load_default(size=18)
 draw.text((16,16),title[:120].replace('—','-'),fill='#17354F',font=font)
 draw.text((16,44),'Model-authored check; fixed coordinates; measurements remain provisional.',fill='#43566A',font=font)
 by_id={p['id']:p for p in points}
 for i,a in enumerate(annotations):
  p=by_id[a['id']];x=p['x']*scale;y=p['y']*scale+header;color={'observed':'#146AB0','unresolved':'#AA6B00','reject':'#B72D37'}.get(a['status'],'#AA6B00')
  draw.ellipse((x-10,y-10,x+10,y+10),outline=color,width=2)
  draw.text((x+12,y-12),str(i+1),font=font,fill=color)
  text=f"{i+1}. {a['id']} [{a['status']}]: {a['label']}"
  # Wrap/limit display only. Full model text is preserved in JSON.
  lines=[];line=''
  for word in text.split():
   nxt=(line+' '+word).strip()
   if line and draw.textlength(nxt,font=font)>side-25:lines.append(line);line=word
   else:line=nxt
  lines.append(line)
  for j,line in enumerate(lines[:2]):draw.text((display.width+12,header+i*row_height+j*23),line,font=font,fill=color)
 path.parent.mkdir(parents=True,exist_ok=True);canvas.save(path)

class VisualCheckProvider:
 """Wrap every image-bearing model call. No opt-out or alternate annotator model."""
 def __init__(self,provider,out,strict=True):self.provider=provider;self.out=Path(out);self.strict=strict
 def complete(self,stage,prompt,images=(),schema=None):
  result=self.provider.complete(stage,prompt,images,schema)
  return self.check(stage,result,images,prompt)
 def check(self,stage,result,images,prompt=""):
  if not images:return result
  self.out.mkdir(parents=True,exist_ok=True)
  # Preserve the primary response even when validation/annotation fails later.
  (self.out/(stage+'.primary.json')).write_text(json.dumps(result,indent=2))
  with Image.open(images[0]) as im:w,h=im.size
  points=anchors_for(result)
  # Review calls contain locations in their prompt; use supplied candidates there.
  if not points and 'Candidate locations: ' in prompt:
   line=prompt.split('Candidate locations: ',1)[1].split('\n',1)[0]
   points=[{'id':p['candidate_id'],**p['pixel']} for p in json.loads(line)]
  if not points:points=[{'id':'stage_summary','x':w/2,'y':h/2}]
  p='Create a visual check of the work in your preceding result below. Do not redo extraction. Return JSON {"annotations":[{"id":"exact supplied ID","label":"short description of what you did or found","status":"observed or unresolved or reject"}],"assessment":"consistent or concerns","notes":[]}. Include each supplied ID exactly once. Do not change coordinates. Include numerical x/y values and printed units from the result in labels when available; never invent units. Image 1 is the exact source. All descriptions are provisional: visual agreement does not prove numerical truth. For a stage summary describe the selection or failure, not an observed measurement.\nFixed anchors: '+json.dumps(points)+'\nYour result: '+json.dumps(result)
  try:
   check=self.provider.complete(stage+'_visual_check',p,images)
   annotations=check.get('annotations',[])
   ids=[a.get('id') for a in annotations]
   if len(ids)!=len(points) or set(ids)!={p['id'] for p in points}:raise VisualCheckError('Visual check must annotate every anchor exactly once')
   if check.get('assessment') not in {'consistent','concerns'}:raise VisualCheckError('Missing visual assessment')
   for a in annotations:
    if not isinstance(a.get('label'),str) or a.get('status') not in {'observed','unresolved','reject'}:raise VisualCheckError('Invalid annotation')
   for point in points:
    if not all(isinstance(point[k],(int,float)) and not isinstance(point[k],bool) and math.isfinite(point[k]) for k in ['x','y']):raise VisualCheckError('Invalid source anchor')
   target=self.out/(stage+'.png');render(images[0],points,annotations,target,stage+' — same-model visual check')
   check.update(image_path=str(target),image_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),source_sha256=hashlib.sha256(Path(images[0]).read_bytes()).hexdigest(),anchors=points,same_provider=True)
   (self.out/(stage+'.json')).write_text(json.dumps(check,indent=2))
   result['_visual_check']=check
   return result
  except Exception as exc:
   (self.out/(stage+'.failure.json')).write_text(json.dumps({'status':'incomplete','error_type':type(exc).__name__,'model_authored_visual_check':False}))
   if self.strict:raise
   # Oversight that cannot be produced is a concern about the stage, not a
   # reason to discard measurements the stage already made.
   result['_visual_check']={'status':'unavailable','assessment':'concerns',
    'error_type':type(exc).__name__,'error':str(exc)[:400],'annotations':[],
    'notes':['visual check unavailable; stage output is unverified'],'same_provider':True}
   return result

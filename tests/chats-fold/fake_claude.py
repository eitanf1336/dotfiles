#!/usr/bin/env python3
import sys,os,json,time,glob,uuid
H=os.path.expanduser('~');A=sys.argv[1:];L=H+'/agents.json'
ag=json.load(open(L)) if os.path.exists(L) else []
if A[:1]==['agents']:print(json.dumps(ag))
elif '--resume' in A and '--bg' in A:
    old=A[A.index('--resume')+1];src=glob.glob(f'{H}/.claude/projects/*/{old}.jsonl')[0]
    n=str(uuid.uuid4());d=open(src).read();cwd=json.loads(d.splitlines()[0])['cwd']
    d+=json.dumps({'type':'user','uuid':str(uuid.uuid4()),'timestamp':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cwd':cwd,'message':{'content':'go on'}},separators=(',',':'))+'\n'
    open(os.path.dirname(src)+f'/{n}.jsonl','w').write(d)
    ag.append({'id':n[:8],'sessionId':n,'kind':'background','status':'idle','cwd':cwd})
    json.dump(ag,open(L,'w'));print('backgrounded · '+n[:8])

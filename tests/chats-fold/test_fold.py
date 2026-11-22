#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pexpect", "pyte"]
# ///
"""Regression test: same-named copies of a chat fold to one row on claude-c.

    uv run --script test_fold.py [chats.py]     (default: the repo copy)

Real keypresses against a fake claude, all in a throwaway HOME."""
import atexit,sys,os,json,shutil,subprocess,tempfile,time,uuid,types,importlib.util
sys.dont_write_bytecode=True
HERE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.abspath(sys.argv[1] if len(sys.argv)>1 else HERE+'/../../python/chats.py')
REAL=os.path.expanduser('~');H=tempfile.mkdtemp(prefix='chats-fold.')
atexit.register(shutil.rmtree,H,True)
C=H+'/.claude/chats';os.makedirs(C);os.makedirs(H+'/.claude/jobs');os.makedirs(H+'/bin')
shutil.copy(SRC,C+'/chats.py');shutil.copy(REAL+'/.claude/chats/projcolor.py',C)
open(H+'/bin/claude','w').write(f'#!/bin/sh\nexec python3 {HERE}/fake_claude.py "$@"\n');os.chmod(H+'/bin/claude',0o755)
os.environ['HOME']=H;os.environ['PATH']=H+'/bin:'+os.environ['PATH'];os.environ.pop('CLAUDE_CONFIG_DIR',None)
ok=bad=0
def check(n,c):
    global ok,bad
    ok+=bool(c);bad+=not c;print('PASS' if c else 'FAIL',n)
def rec(ts,text,cwd,u=None,k='user',**x):
    return dict({'type':k,'uuid':u or str(uuid.uuid4()),'timestamp':ts,'cwd':cwd,'message':{'content':text}},**x)
def title(t):return {'type':'ai-title','aiTitle':t}
def put(sid,recs,name,root=None,cwd='/p/one'):
    d=(root or H+'/.claude/projects')+'/'+cwd.replace('/','-');os.makedirs(d,exist_ok=True)
    with open(f'{d}/{sid}.jsonl','w') as f:
        for r in recs+[title(name)]:f.write(json.dumps(r,separators=(',',':'))+'\n')
def store(n,d):json.dump(d,open(f'{C}/{n}.json','w'))
def load(n):
    try:return json.load(open(f'{C}/{n}.json'))
    except Exception:return {}
S=lambda n:f'{n:08x}-0000-4000-8000-000000000000'
T=lambda n:f'2026-11-{n:02d}T10:00:00Z'
P='/p/one';cat={}
def chat(n,recs,name,**k):put(S(n),recs,name,**k);cat[S(n)]='In Progress'
b=[rec(T(1),'base',P)]
chat(1,b+[rec(T(2),'a',P)],'siblings');chat(2,b+[rec(T(5),'b',P)],'siblings')
chat(3,b+[rec(T(3),'c',P),rec(T(9),'woke by itself',P,k='assistant')],'siblings')
chat(4,[rec(T(1),'x',P)],'same words');chat(5,[rec(T(2),'y',P)],'same words')
z=str(uuid.uuid4())
chat(6,[rec(T(1),'x',P,u=z)],'nested id')
chat(7,[rec(T(2),'y',P,toolUseResult={'uuid':z,'v':1})],'nested id')
r=[rec(T(1),'role',P)];chat(8,r,'role');chat(9,r+[rec(T(2),'n',P)],'role')
r=[rec(T(1),'park',P)];chat(10,r,'parked');chat(11,r+[rec(T(2),'n',P)],'parked')
r=[rec(T(1),'move',P)];chat(12,r,'two projects');chat(13,[dict(x,cwd='/p/two') for x in r+[rec(T(2),'n',P)]],'two projects',cwd='/p/two')
r=[rec(T(1),'star',P)];chat(14,r,'starred old');chat(15,r+[rec(T(2),'n',P)],'starred old')
chat(16,[rec(T(1),'q',P)],'linked');chat(17,[rec(T(2),'summary',P)],'linked')
r=[rec(T(1),'queue',P)];chat(18,r+[dict(rec(T(8),'',P,k='attachment'),attachment={'type':'queued_command','commandMode':'prompt','prompt':'mid turn'})],'queued')
chat(19,r+[rec(T(4),'n',P)],'queued')
r=[rec(T(1),'ren',P)];chat(20,r,'to rename');chat(21,r+[rec(T(2),'n',P)],'to rename')
put(S(50),[rec(T(1),'m',P)],'moved old');cat[S(50)]='Done'
put(S(51),[rec(T(2),'n','/p/else')],'moved new',cwd='/p/else')
store('chat_projects',{S(51):P})
store('categories',cat);store('badges',{S(8):'ROLE'});store('paused',{S(10):time.time()})
store('starred',{S(14):True});store('superseded',{S(16):S(17),S(50):S(51)})
spec=importlib.util.spec_from_file_location('chats',C+'/chats.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def app(**k):return m.App(None,select_project=None,**k)
def vis(a):return {c['id'] for c in a.visible_chats()}
before={n:load(n) for n in('categories','starred','superseded')}
a=app();v=vis(a);has=lambda *n:all(S(i) in v for i in n);no=lambda *n:not any(S(i) in v for i in n)
check('In Progress siblings: only the one typed in last',has(2) and no(1,3))
check('unrelated same name: both stay',has(4,5))
check('uuid inside a tool result is not proof',has(6,7))
check('moved continuation hides on the first paint',S(50) not in v)
check('badged chat never folds',has(8,9));check('paused chat never folds',has(10,11))
check('other project: both stay',has(12,13));check('older starred folds in normal view',has(15) and no(14))
check('saved link is proof without shared ids',has(17) and no(16))
check('message typed mid-turn counts',has(18) and no(19))
a.marked_only=True;check('marked view keeps the starred older copy',S(14) in vis(a));a.marked_only=False
a.show_older=True;check('show-older reveals all',len(vis(a))==22)
check('folding writes no board state',before=={n:load(n) for n in before})
check('session restore can open an older copy',S(1)[:8] in {x[:8] for x in vis(app(select_id=S(1),auto_open=True))})
check('cached second start gives same answer',vis(app())==v)
a=app();check('fork gets its own name',hasattr(a,'unique_fork_name') and a.unique_fork_name('x ⑂')=='x ⑂1')
d=dict(load('superseded'));d[S(4)]=S(99);store('superseded',d)
a=app();a._agents_ts=1;a.live_ids=set();a.superseded_map=m.load_superseded();a.rescan()
check('link survives a late file',load('superseded').get(S(4))==S(99))

# remote resume, mirror arrives late
R=H+'/.claude/remote/srv/projects';os.makedirs(R)
r=[rec(T(1),'remote',P)];put(S(30),r,'remote chat',root=R)
c=load('categories');c[S(30)]='In Progress';store('categories',c);store('starred',dict(load('starred'),**{S(30):True}))
a=app();target=next(c for c in a.all_chats if c['id']==S(30))
m.remote_trust=lambda *x:None;m.run_child=lambda *x,**k:None;m.set_window_title=lambda *x:None
m._remote_attach_cmd=lambda *x:['true']
def remote(n,action):
    m.remote_run=lambda *x,**k:types.SimpleNamespace(returncode=0,stdout='backgrounded · '+S(n)[:8],stderr='')
    m.remote_agents_now=lambda *x:{S(n):{'id':S(n)[:8]}}
    m.open_remote_chat(a,target,action)
remote(31,'resume')
a=app();a._agents_ts=1;a.live_ids=set();a.rescan()
check('remote link survives mirror lag',load('superseded').get(S(30))==S(31))
put(S(31),r+[rec(T(6),'go on',P)],'remote chat',root=R);v=vis(app())
check('remote resume shows once',S(31) in v and S(30) not in v)
check('remote resume carries the star',S(31) in load('starred'))
a=app();target=next(c for c in a.all_chats if c['id']==S(30));remote(32,'fork')
put(S(32),r+[rec(T(7),'branch',P)],'remote chat',root=R);v=vis(app())
check('remote fork is named and visible beside it',load('names').get(S(32))=='remote chat ⑂1' and {S(31),S(32)}<=v)

# real keypresses
K='/p/keys'
import pexpect,pyte
P_=None;SC=None;ST=None
def pump(w):
    end=time.time()+w
    while time.time()<end:
        try:ST.feed(P_.read_nonblocking(200000,timeout=.15))
        except pexpect.TIMEOUT:pass
        except pexpect.EOF:time.sleep(.2)
def screen():return '\n'.join(SC.display)
def rows(t):return sum(t in l and '[' in l for l in SC.display)
def send(x,w):P_.send(x);pump(w)
def boot(q,proj):
    global P_,SC,ST
    if P_:P_.terminate(force=True)
    json.dump({'active':proj,'list':{P:'',K:''}},open(C+'/projects.json','w'))
    SC=pyte.Screen(170,55);ST=pyte.Stream(SC)
    env=dict(os.environ,HOME=H,TERM='xterm-256color',LANG='en_US.UTF-8')
    P_=pexpect.spawn('/usr/bin/python3',['-B',C+'/chats.py'],env=env,dimensions=(55,170),encoding='utf-8',codec_errors='replace')
    pump(4)
    if q:
        send('/',.8);send(q,.4);send('\r',1.2)
KEYS={'Enter':'\r','BSpace':'\x7f'}
def key(*k,w=3.5):
    for x in k:send(KEYS.get(x,x),.05)
    pump(w)
put(S(40),[rec(T(1),'first',K)],'daily resume',cwd=K);put(S(41),[rec(T(1),'first f',K)],'forked chat',cwd=K)
c=load('categories');c.update({S(40):'In Progress',S(41):'In Progress'});store('categories',c)
boot('daily resume',K);key('Enter',w=7)
check('Enter resume of In Progress: one row',rows('daily resume')==1)
boot('forked chat',K);key('f',w=7)
check('f fork: two differently named rows','forked chat ⑂1' in screen() and rows('forked chat')==2)
boot('to rename',P);check('board shows one row',rows('to rename')==1)
key('a');check('key a reveals',rows('to rename')==2)
key('a');check('key a folds again',rows('to rename')==1)
boot('to rename',P);key('r',w=1);key(*['BSpace']*25,w=1);send('renamed',.5);key('Enter')
check('rename keeps copies folded',rows('renamed')==1 and rows('to rename')==0)
check('board did not crash','Traceback' not in screen())
P_.terminate(force=True)
print('TOTAL',ok,'passed',bad,'failed')
sys.exit(bool(bad))

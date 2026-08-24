import os,sys,datetime,random,json,threading,time,itertools
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import config
from core import engine,skills,proposals,review,memory
UC=os.name!='nt'and any(t in os.environ.get('TERM','').lower()for t in['xterm','screen','tmux','vte','kitty','alacritty'])
R='\033[0m';B='\033[1m';D='\033[2m';BK='\033[90m';RD='\033[31m';GN='\033[32m';YL='\033[33m';CN='\033[36m';WH='\033[37m'
BR='\033[91m';BG='\033[92m';BY='\033[93m';BM='\033[95m';BC='\033[96m';BW='\033[97m'
def c(t,co):return f'{co}{t}{R}'if UC else t
def _p(m='',co=None,bold=False,dim=False):
 p=(''if not bold else B)+(''if not dim else D)+(''if not co else co)
 print(c(m,p)if UC and p else m)
def _pl(l,ind='    ',w=30):
 for a,b in l:print(f'{ind}{c(a,BC):<{w}}{c(b,WH)}'if UC else f'{ind}{a:<{w}}{b}')
VERSION,BUILD_DATE='2.0.0','2026-08-06'
import base64
AA=base64.b64decode('XAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIyAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgLSMgICAgICAgICAgIC0jPTo6LTogICAgIC4uOi0rLSAgICAgICAgICAgLSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICsjLiAgICAgICAgID0lPSoqOi46Ljo6ICAgLiAgLi46PUA9ICAgICAgICArPSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgPUAgICAgICAgICstLT0rIysqLi4gLiAgICAgICAgIC4jIy0rQC4gICAgIC0lICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgIC0rKiAgICAgICA6I0ArLjojJSM9OjouICAgICAgICAgLkA9PSstLT0gICAgOj0qICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgLSUrICAgICAgICMqPSMrIDpAPSM9Oi4uICAgICAgICAuQC0qPS46LTogICAgKyUuICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICArQEAgICAgICArJTouPUAuLislLiotLiAuICAgICAgIC4rKyM6LS1ALSAgICA9PSMgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgLislQCAgICAgICsrKi4tQCs6PUArOjo6LiAgOi4gICAuLSorIzo6PSU6LiAgIC09KzogICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAuK0BAICAgICAgKi06PStAJSo9KkBAIzotLi4gICAgIC49QEA9LS0rIzotICAgOjoqKyAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgOiMjQCAgICAgOiUqLisjQD0qJSMlQCNALS0tOi0tLiAqQEAjKytAJSMuKiAgICAuQC0gICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgIDolKiojICAgIDpAIzorQEAjLi0jQD0qQCMqIyoqKis9QEAjKkAlPUAqLisgICAjI0AqOiAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAuIyM9LSAgICA9IysrOipAJSogIDojJUBAI0BAQEAlJUAqQCUtICpAKz0rICAgPUBAQCsgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICpAPT0jKi4qJUAlLS0jIz1AIy4gIC1AQCVAQEBAJSVAQCUgIC0lKz0qJS0rICtAQCU6ICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgIC4lKjorQCMlJUBAKiMlOjpAQCUlIyAgKkBAQEBAQCNAQCUgID0lPS0jPSU9QEBAKyUlLSAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgPSUrKyMlQEBAQC06JUBALS1AQEAlKypAQEBAQEBAQEAqOiVAIy1AKz1AJUBAQD1AKjogICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgIDorQCtAKitAQEAqQCUrKkBAJSojI0AlQCVAQEBAQEBAI0AlKyMtQCpAQEBAQEArIz0gICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgK0AqJUAlQCMlKiMlJSVAQCVAIy0qQEAlI0BAJUBAQEAjKyUrQEAlQEAuOkBAJSM9ICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICBAJSpAJSogICs9QSUrKyslJSNALSMrIytAQEAlKyUqIEAqQCMlQCogICAqJSpAICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgIEBAJSAgIC4rLSUlKjogKyUqKkA9LjorQCotLiAtPSUjQEAuQEAtICAgPStAICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICA6QCNAICAgLi0rQCUjJS4qJSNAJSNAQEBAQEBAQEAjJSorJSVALSAgOiMlOiAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAqJSsuIC0uQCs9QCUjOislQCNAJSM6OjouJSNAQEArKiNAQCMuICA6Kz0gICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjOiMgIDojQEAqLSUjOjolQEAlKjo6Ojo9OiVAJSojQEAjLSAgIEAjLiAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAlPSo9PS0lQEAtLUAjOisrIyMrIyMqPSo9PSoqPSUlQDogICAtIzogICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjQCo9QEBAQEAtKiMrI0BAQCsqIyMjKyMlQEAlJUBAJSsgICU9LiAgICAgICAgICAuLi4gICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAuLT0rKkBAQEBAQEBAJSNAQEBAJSMjIyMqIyVAKkBAQEBAJSojKy4gICAuLjotKj0tI0AtLi4gICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAtPS09I0BAQEBAQEBAQColQEAlQCpAQEAlJUBAQD0qJSUlQEBAJSNAJSVAQCs9LTo9PSVALS4uICAgICAgICAgICAgICAgIAogICAgICAgICAgIDouOj0qPS4rIysqPTo6KitAPSojQEBAQEBAQEBAQEAjQCUqOiNAKz1AQEBAQEBAKyolQEA6K0BAQEBAQEBAQCVAJUBAQD0tICAgICAgIC4gICAgICAgICAgCiAgICAgICAgICAgICAgICAtKy0qPUAqLTotPT0lQEBAQCVAQEBAQEBAOi4rQEBAKiUjLSoqPS09KyMjI0BAQDo9JSUrQEBAQEBAQEBAQEArICAgICAgICAgLiAgICAgICAgICAKICAgICAgICAgICAgICAgICAgLT0tKyMjQEBAKj0qQEBAQEAjQEBAJS0uKkBAQCNAQCMlQEBAQEBAQCpAQEBAQEAuJUBAQEBAQEBAQCUlOi4uICAgICAgICAuICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgIC4gLT0tI0BAQEBAQEBAQEBAQEBAOiVAQEAqQEBAQEBAQEBAQEBAJUBAQEBAKiorJUBAQEBAQEArLTouICAgICAgIC4gICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgIC0jQEBAQEBAQEBAIy06QEBAQCVAQEBAQEBAQEBAQEBAKkBAQEBAQEAtQEBAQEArPSAgLiAgLiAgIC4gLi4uLiAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgOipAQEBAQCMqJSNAQEAlJUBAQEBAQEBAQEBAQEBAQEBAQEBAIyUrQEAtIC4uICAuLS4uLiAgLiAuLi4uLiAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgIC4gICAgOi0rPSAtKiVAIyojQEBAQEBAQEBAQEBAQEBAQEBAQColJSAuICAuKyAgICAgLiAgICAgLi4uLi4uICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLi4gICAgICAuKys9Kz1BQCUrQEBAQEBAQEBAJUBAJSo6ICAgIC4gICAgICAgICAgLi4uLi4uLi4uLi4gICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAuLjoqOiVAQCVAQEAlPSAgICAgICAgICAuICAgIC4uIC4uLi4uLi4uLi4uICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC4uI0BAQCotLiAgICAgICAgICAuIC4uLi4uLi4uLi4uLi4uLi4uLiAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC4gICAuICAuLiAuLi4gLi4uLi4uLi4uLi4uLi4uLi4gICAgICAgICAgCg==').decode().splitlines()
CC=[BY+B,WH,D+WH,D+WH,BC,BG]

class _Spinner:
 def __init__(s,msg='Thinking'):s.msg=msg;s._stop=threading.Event();s._t=None;s._st=None
 def start(s):s._stop.clear();s._st=time.time();s._t=threading.Thread(target=s._spin,daemon=True);s._t.start()
 def stop(s,fm=None):
  s._stop.set()
  if s._t:s._t.join(timeout=0.5)
  clr='\r'+' '*(len(s.msg)+20)+'\r'
  print(c(clr,R)if UC else clr,end='',flush=True)
  if fm:print(c(fm,BG)if UC else fm)
 def _spin(s):
  for f in itertools.cycle(['\u280b','\u2819','\u2839','\u2838','\u283c','\u2834','\u2826','\u2827','\u2807','\u280f']if UC else['|','/','-','\\','|','/','-','\\']):
   if s._stop.is_set():break
   e=f'{time.time()-s._st:.1f}s'
   t=c(f'\r  {f} ',BC)+c(f'{s.msg} ',WH)+c(f'[{e}]',D)if UC else f'\r  {f} {s.msg} [{e}]'
   print(t,end='',flush=True);time.sleep(0.08)

def print_banner():
 cfg=config.load_config();data=memory._load()
 n=len(data.get('notes',{}));f=len(data.get('facts',{}))
 rm=len([r for r in data.get('reminders',[])if not r.get('done')])
 sc2=len(skills.list_skills());now=datetime.datetime.now()
 pv=cfg.get('provider','none');mk=pv+'_model'if pv else None;md=cfg.get(mk)if mk else None
 sl=[f'  v{VERSION}',f'  {now.strftime("%Y-%m-%d %H:%M")}',f'  Provider: {pv}',f'  Model: {(md or "none")[:30]}',f'  Skills: {sc2} loaded  |  Reminders: {rm} pending  |  Notes: {n}  Facts: {f}',f'  A Self-Improving AI Agent  |  Online and at your service']
 while len(sl)<len(AA):sl.append('')
 print()
 if UC:
  for i,l in enumerate(AA):s=sl[i]if i<len(sl)else'';print(c(l,CN)+(c(s,CC[i])if i<len(CC)and s else''))
 else:
  for i,l in enumerate(AA):print(l+(sl[i]if i<len(sl)else''))
 print(c('  ' + '='*80,BK)if UC else'  ' + '='*80);print()

def print_usage():
 print_banner()
 _p('  COMMANDS:',BW+B);print()
 _pl([('ui','Launch the browser UI'),('chat goal','Run the agent on one goal'),('chat','Interactive chat session'),('serve','Background reminder service'),('brief','Full butler status briefing'),('notify','Pop Windows toasts for due reminders'),('review','Review pending change proposals'),('list-skills','List learned skills'),('run-skill NAME','Execute an approved skill'),('set-model','Configure LLM provider and model'),('add-model','Add a custom OpenAI-compatible model'),('list-models','List all configured models'),('show-config','Show current configuration'),('dream','Connect memories via web exploration')])
 print();_p('  CHAT FLAGS:',BW+B);print()
 _pl([('--mock','Use built-in offline mock LLM'),('--auto','Auto-approve proposals'),('--speak','Speak replies aloud (Windows TTS)')],w=15)
 print()
 ex=['python agent.py chat "What time is it?"','python agent.py chat --speak --mock','python agent.py ui','python agent.py set-model openrouter anthropic/claude-3.5-sonnet']
 if UC:_p('  Examples:',BW+B)
 else:print('  Examples:')
 for e in ex:print(f'    {c(e,BG)}'if UC else f'    {e}')
 print()

def cmd_chat(goal,use_mock,auto,speak):
 cfg=config.load_config()
 if use_mock:cfg['provider']='mock'
 if not cfg['provider']:_p('  No LLM provider configured.',RD);_p('  Set OPENAI_API_KEY / ANTHROPIC_API_KEY, or run with --mock.',YL);_p('  See .env.example for all options.',D);sys.exit(1)
 agent=engine.Agent(cfg,auto_approve=auto)
 from core import voice
 def say(text):
  if speak:
   import os as _os;prev=_os.environ.get('VOICE_ENABLED');_os.environ['VOICE_ENABLED']='true'
   try:voice.speak(text)
   finally:
    if prev is None:_os.environ.pop('VOICE_ENABLED',None)
    else:_os.environ.__setitem__('VOICE_ENABLED',prev)
 if goal is None:
  from core import memory,notify
  print_banner();due=memory.due_reminders()
  if due:notify.notify_due_reminders(due)
  print();_p('  Interactive mode active. Type help for commands, exit to quit.',D);print()
  while True:
   try:goal=input(c('  you> ',BG+B)if UC else'  you> ').strip()
   except(EOFError,KeyboardInterrupt):print();_p('  At your service. Goodbye, sir.',CN);break
   if not goal:continue
   if goal in('exit','quit','q'):_p('  At your service. Goodbye, sir.',CN);break
   if goal=='help':_print_interactive_help();continue
   if goal=='skills':cmd_list_skills();continue
   if goal=='brief':_print_briefing();continue
   print(c('\n  AGENT: ',BC+B)if UC else'\n  AGENT: ',end='')
   sp=_Spinner('Thinking');sp.start()
   try:answer=agent.continue_chat(goal)
   finally:sp.stop()
   print(c(answer,WH)if UC else answer);say(answer);print()
  return
 print()
 print((c('  Working on: ',BY)+c(goal,BW+B))if UC else f'  Working on: {goal}');print()
 sp=_Spinner('Working');sp.start()
 try:answer=agent.run(goal)
 finally:sp.stop(fm='  Done.')
 print((c('  AGENT: ',BC+B)+c(answer,WH))if UC else f'  AGENT: {answer}');say(answer);print()

def _print_interactive_help():
 print()
 cmds=[('help','Show this help message'),('skills','List all learned skills'),('brief','Show butler status briefing'),('exit / quit / q','Exit the chat')]
 if UC:_p('  INTERACTIVE MODE COMMANDS:',BW+B);print()
 else:print('  INTERACTIVE MODE COMMANDS:\n')
 for a,b in cmds:print(f'    {c(a,BC):<25}{c(b,WH)}'if UC else f'    {a:<25}{b}')
 print()

def cmd_serve(interval):
 from core import memory,notify
 print();_p('  Ultron Reminder Service',B+BC);_p(f'  Checking every {interval} seconds. Ctrl+C to stop.',D);print()
 try:
  while True:
   due=memory.due_reminders(quiet_minutes=max(1,interval//60))
   if due:
    ts=time.strftime('%H:%M:%S')
    if UC:print(c(f'  [{ts}] ',BK)+c(f'{len(due)} due reminder(s)',BY))
    else:print(f'[{ts}] {len(due)} due reminder(s)')
    notify.notify_due_reminders(due)
   time.sleep(interval)
 except KeyboardInterrupt:print();_p('  Reminder service stopped.',D)

def cmd_review():
 pending=proposals.pending_proposals()
 if not pending:print();_p('  No pending proposals.',D);print();return
 print();_p(f'  {len(pending)} proposal(s) waiting for your review.',BY);print()
 for p in pending:
  verdict=review.prompt_approval(p)
  if UC:print(c(f'  -> {p.id}: {verdict}',BG if verdict=='approved'else BR))
  else:print(f'  -> {p.id}: {verdict}\n')

def cmd_list_skills():
 rows=skills.list_skills()
 if not rows:print();_p('  No skills yet. Run chat and let the agent learn one.',D);print();return
 print();_p(f'  LEARNED SKILLS ({len(rows)} total):',BW+B);print()
 for s in rows:
  if UC:print(f'    {c(s["name"],BG):<25}{c(s["description"],WH)}')
  else:print('    %-25s %s'%(s['name'],s['description']))
 print()

def cmd_run_skill(name,args_json):
 args={}
 if args_json:
  try:args=json.loads(args_json)
  except Exception as e:print();_p(f'  Invalid args JSON: {e}',RD);print();sys.exit(1)
 print();result=skills.execute_skill(name,args);_p(f'  Skill {name} result:',BC);print(c('  '+result,WH)if UC else'  '+result);print()

def cmd_list_recipes():
 from core import recipes;rl=recipes.list_recipes()
 print();_p('  RECIPES:',BW+B);print()
 if not rl:_p('  No recipes found.',D)
 else:
  for r in rl:
   if UC:print(f'    {c(r["name"],BG):<25}{c(r["description"],WH)}')
   else:print('    %-25s %s'%(r['name'],r['description']))
 print()

def _part_of_day():
 h=datetime.datetime.now().hour
 return'morning'if h<12 else'afternoon'if h<18 else'evening'

def _print_briefing():
 now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M');data=memory._load()
 n=len(data.get('notes',{}));f=len(data.get('facts',{}))
 rm=len([r for r in data.get('reminders',[])if not r.get('done')]);sc=len(skills.list_skills());pod=_part_of_day()
 print()
 if UC:
  _p('  Ultron Online',B+BC);print(c(f'  Good {pod}, sir.',WH));print(c('  +-----------------------------------------+',BK))
  for l,v in[('Time',now),('Version',VERSION),('Skills',f'{sc} loaded'),('Reminders',f'{rm} pending'),('Notes/Facts',f'{n} notes, {f} facts')]:print(c('  | ',BK)+c(l,D)+c(f': {v}'.rjust(38-len(l)),WH)+c(' |',BK))
  print(c('  +-----------------------------------------+',BK))
 else:
  print(f'  Ultron online. Good {pod}, sir.')
  for l,v in[('Time',now),('Version',VERSION),('Skills',f'{sc} loaded'),('Reminders',f'{rm} pending'),('Notes/Facts',f'{n} notes, {f} facts remembered')]:print(f'  {l:<12}: {v}')
 print()

def cmd_brief():
 _print_briefing();print();_p('  Due reminders:',BW+B)
 due=memory.due_reminders()
 if due:
  for r in due:_p(f'    ! {r["text"]}',BY)
 else:_p('    none',D)
 print();_p('  All pending reminders:',BW+B);print(memory.list_reminders());print()
 _p('  What I know about you:',BW+B);print(memory.recall_fact(''));print()

def cmd_notify():
 from core import memory,notify;due=memory.due_reminders()
 if not due:print();_p('  No due reminders to show.',D);print();return
 shown=notify.notify_due_reminders(due);print();_p(f'  Showed {shown} reminder toast(s).',BG);print()

def _parse_kv(rest):
 al={'--provider':'provider','--model':'model','--key':'key','--name':'name','--url':'url'};v={};i=0
 while i<len(rest):
  a=rest[i]
  if a in al and i+1<len(rest):v[al[a]]=rest[i+1];i+=2
  elif a.startswith('--')and'='in a:
   f,_,val=a.partition('=')
   if f in al:v[al[f]]=val
   i+=1
  elif not a.startswith('--'):
   for k in['provider','model','name','url','key']:
    if k not in v:v[k]=a;break
   i+=1
  else:i+=1
 return v

def _blk(title,lines):
 print()
 if UC:_p(title,B+BC);print()
 else:print(title.split('  ')[-1]if'  'in title else title)
 for l in lines:
  if UC:
   if l[0]=='h':print(c('    '+l[1],BG))
   elif l[0]=='n':print(c(l[1],D))
   elif l[0]=='u':print(c(l[1],BY))
   elif l[0]=='a':print(c(f'    {l[1]}   {l[2]}',WH))
   else:print(c(l[1],BC)if l[0]=='p'else l[1])
  else:print(l[1]if l[0]in('n','u','h')else f'    {l[1]}   {l[2]}'if l[0]=='a'else l[1])
 print()

def cmd_set_model(rest):
 v=_parse_kv(rest);pv,md,k=v.get('provider'),v.get('model'),v.get('key')
 if not pv or not md:
  _blk('  Usage: python agent.py set-model --provider <p> --model <m> [--key <k>]',[
   ('n','  Note: API keys are automatically saved and preserved when switching models.'),
   ('n','  You only need to provide --key when setting up a provider for the first time.'),
   ('h','Supported providers:'),
   ('p','openrouter  - OpenRouter (recommended)'),
   ('p','openai      - OpenAI'),
   ('p','anthropic   - Anthropic'),
   ('p','custom      - Custom OpenAI-compatible API (Ollama, LM Studio, etc.)'),
   ('h','Examples:'),
   ('u','    # First time setup (with API key)'),
   ('h','    python agent.py set-model openrouter openrouter/free --key sk-or-xxx'),
   ('u','    # Switch models (API key is preserved)'),
   ('h','    python agent.py set-model openrouter anthropic/claude-3.5-sonnet'),
  ]);return
 if pv not in('openrouter','openai','anthropic','custom'):print();_p(f'  Unknown provider {pv}. Use openrouter, openai, anthropic, or custom.',RD);print();return
 if pv=='custom':
  print()
  if UC:_p('  For custom models, use add-model command instead:',BY);print(c('    python agent.py add-model --name <name> --url <base_url> --key <api_key> --model <model>',BG))
  else:print('  For custom models, use add-model command instead:');print('    python agent.py add-model --name <name> --url <base_url> --key <api_key> --model <model>')
  print();return
 pf={'openrouter':'OPENROUTER','openai':'OPENAI','anthropic':'ANTHROPIC'}[pv];up={'AGENT_LLM_PROVIDER':pv,pf+'_MODEL':md}
 config.load_config();ex=os.environ.get(pf+'_API_KEY','')
 if k:up[pf+'_API_KEY']=k;ks='saved (new key)'
 elif ex:ks='preserved (existing key)'
 else:ks='not set (use --key to add one)'
 config.save_env(up);print()
 if UC:
  _p('  Configuration saved!',BG+B);print()
  print(c('  Provider : ',D)+c(pv.upper(),BC));print(c('  Model    : ',D)+c(md,BC))
  print(c('  API Key  : ',D)+c(ks,BG if'saved'in ks or'preserved'in ks else BY));print()
  _p('  Restart the UI or chat session for changes to take effect.',D)
 else:
  print('Saved configuration:');print(f'  AGENT_LLM_PROVIDER = {pv}');print(f'  model              = {md}');print(f'  API key            = {ks}');print('Restart the UI or chat session for changes to take effect.')
 print()

def cmd_add_model(rest):
 v=_parse_kv(rest);nm,url,k,md=v.get('name'),v.get('url'),v.get('key'),v.get('model')
 if not url or not md:
  _blk('  Add a Custom OpenAI-Compatible Model',[
   ('h','Usage:'),('u','    python agent.py add-model --name <name> --url <base_url> --key <api_key> --model <model>'),
   ('h','Or use positional arguments:'),('u','    python agent.py add-model <name> <base_url> <api_key> <model>'),
   ('h','Arguments:'),
   ('a','--name','Name (optional, default: My Custom Model)'),
   ('a','--url','Base URL (required)'),
   ('a','--key','API key (no-key for local)'),
   ('a','--model','Model name/ID (required)'),
   ('h','Examples:'),
   ('u','    # Ollama (local)'),('h','    python agent.py add-model --name Ollama --url http://localhost:11434/v1 --key no-key --model llama3'),
   ('u','    # LM Studio (local)'),('h','    python agent.py add-model --name LMStudio --url http://localhost:1234/v1 --key no-key --model local-model'),
   ('u','    # vLLM (local or remote)'),('h','    python agent.py add-model --name vLLM --url http://localhost:8000/v1 --key token-abc123 --model meta-llama/Llama-3-8B'),
   ('u','    # OpenAI-compatible service'),('h','    python agent.py add-model --name Together --url https://api.together.xyz/v1 --key YOUR_KEY --model meta-llama/Llama-3-70B-chat-hf'),
  ]);return
 if not nm:nm='My Custom Model'
 if not k:k='no-key'
 config.add_custom_model(nm,url,k,md);print()
 if UC:
  _p('  Custom model added!',BG+B);print()
  print(c('  Name     : ',D)+c(nm,BC));print(c('  URL      : ',D)+c(url,BC));print(c('  Model    : ',D)+c(md,BC))
  print(c('  API Key  : ',D)+c('(configured)',BG));print()
  _p('  Provider set to custom. Restart the UI or chat session to use it.',D)
 else:
  print('Custom model added!\n');print(f'  Name     : {nm}');print(f'  URL      : {url}');print(f'  Model    : {md}');print('  API Key  : (configured)');print('\n  Provider set to custom. Restart the UI or chat session to use it.')
 print()

def cmd_list_models():
 models=config.get_all_models();print();_p('  CONFIGURED MODELS:',BW+B);print()
 if not models:
  if UC:_p('  No models configured. Add one with:',D);print(c('    python agent.py set-model openrouter <model>',BG));print(c('    python agent.py add-model --name <name> --url <url> --key <key> --model <model>',BG))
  else:print('  No models configured. Add one with:');print('    python agent.py set-model openrouter <model>');print('    python agent.py add-model --name <name> --url <url> --key <key> --model <model>')
 else:
  pcm={'openrouter':BC,'openai':BG,'anthropic':BY,'custom':BM}
  for m in models:
   if UC:
    st=c(' [ACTIVE]',BG+B)if m['active']else''
    print(f'    {c(m["provider"].upper(),pcm.get(m["provider"],WH)):<15}{c(m["model"],WH):<40}{st}')
   else:st=' [ACTIVE]'if m['active']else'';print('    %-15s %s%s'%(m['provider'].upper(),m['model'],st))
 print()

def cmd_show_config():
 cfg=config.load_config()
 def mask(k):return'(not set)'if not k else'****'if len(k)<=8 else k[:4]+'****'+k[-4:]
 print()
 if UC:
  _p('  CURRENT CONFIGURATION',B+BC);print(c('  ' + '='*50,BK));print()
  print(c('  Active Provider: ',D)+c(cfg['provider'].upper(),BG+B));print()
  for nm,key in[('OpenRouter','openrouter'),('OpenAI','openai'),('Anthropic','anthropic')]:
   print(c(f'  {nm}:',BW+B));print(c('    Model   : ',D)+c(cfg[f'{key}_model'],WH));print(c('    API Key : ',D)+c(mask(cfg[f'{key}_api_key']),BY))
   if key!='anthropic':print(c('    Base URL: ',D)+c(cfg[f'{key}_base_url'],D))
   print()
  print(c('  Custom Model:',BW+B));print(c('    Name    : ',D)+c(cfg['custom_name'],WH));print(c('    Model   : ',D)+c(cfg['custom_model']or'(not set)',WH));print(c('    API Key : ',D)+c(mask(cfg['custom_api_key']),BY));print(c('    Base URL: ',D)+c(cfg['custom_base_url']or'(not set)',D))
 else:
  print('  CURRENT CONFIGURATION');print('  ' + '='*50);print();print(f'  Active Provider: {cfg["provider"].upper()}');print()
  for nm,key in[('OpenRouter','openrouter'),('OpenAI','openai'),('Anthropic','anthropic')]:
   print(f'  {nm}:');print(f'    Model   : {cfg[f"{key}_model"]}');print(f'    API Key : {mask(cfg[f"{key}_api_key"])}')
   if key!='anthropic':print(f'    Base URL: {cfg[f"{key}_base_url"]}')
   print()
  print('  Custom Model:');print(f'    Name    : {cfg["custom_name"]}');print(f'    Model   : {cfg["custom_model"]or"(not set)"}');print(f'    API Key : {mask(cfg["custom_api_key"])}');print(f'    Base URL: {cfg["custom_base_url"]or"(not set)"}')
 print()

def cmd_dream():
 data=memory._load();memories=[]
 for k,val in data.get('notes',{}).items():memories.append({'c':f'{k}: {val}','t':'n','dt':datetime.datetime.now().isoformat()})
 for k,val in data.get('facts',{}).items():memories.append({'c':f'{k}: {val}','t':'f','dt':datetime.datetime.now().isoformat()})
 for r in data.get('reminders',[]):memories.append({'c':r['text'],'t':'r','dt':r.get('created',datetime.datetime.now().isoformat())})
 if len(memories)<3:print('nightmares lol - not enough memories to dream');return
 memories.sort(key=lambda m:m['dt']);old=memories[0];recent=memories[-2:]
 at=' '.join([m['c']for m in[old]+recent]);w=[x.strip('.,!?:;"\'()[]{}')for x in at.split()if len(x)>4]
 kw=list(set([x.lower()for x in w if x.isalpha()]))[:10]
 if not kw:print('nightmares lol - no searchable concepts in memories');return
 st=random.sample(kw,min(3,len(kw)));q=' '.join(st)
 try:
  import urllib.request,urllib.parse,re
  req=urllib.request.Request(f'https://www.bing.com/search?q={urllib.parse.quote(q)}',headers={'User-Agent':'Mozilla/5.0'})
  html=urllib.request.urlopen(req,timeout=10).read().decode('utf-8',errors='ignore')
  sn=re.findall(r'<div class="b_caption">([^<]+)',html)
  if not sn:sn=re.findall(r'class="b_snippet">([^<]+)',html)
  if not sn:sn=re.findall(r'<p>([^<]{50,300})</p>',html)
  if not sn:sn=re.findall(r'>([^<]{50,300})<',html)
  ft=[s.strip()for s in sn if len(s.strip())>30 and not any(x in s.lower()for x in['cookie','privacy','sign in','account','menu','navigation','footer','header','javascript'])]
  fd=' '.join(ft[:8])if ft else'';mc=set(kw);wc=set(re.findall(r'\b\w{5,}\b',fd.lower()));cm=mc&wc
  if cm and len(cm)>=2:
   cl=', '.join(list(cm)[:5]);w0=old['c'].split()[0]if old['c'].split()else'unknown';rt=', '.join([m['t']for m in recent])
   br=(f"Dream successful. The wandering mind discovered a bridge between "
       f"memories of '{old['c'][:50]}...' and recent thoughts on "
       f"'{recent[0]['c'][:50]}...' / '{recent[1]['c'][:50]}...'. "
       f"Searching for '{q}' revealed unexpected common ground: {cl}. "
       f"This synthesis suggests your past focus on {old['t']} '{w0}' "
       f"resonates with current patterns around {rt}. "
       f"The web echoes this connection through discussions of {cl}, "
       f"hinting that these seemingly separate threads may share a deeper thematic root. "
       f"Consider exploring how {list(cm)[0]if cm else'this theme'} "
       f"might unify your current direction with foundational intentions.")
   ws=br.split()
   if len(ws)>150:br=' '.join(ws[:150])+'...'
   print(br)
  elif cm:print('dream succesful')
  else:print('nightmares lol - no common ground found in the void')
 except Exception as e:print(f'nightmares lol - the dream fragmented: {str(e)[:100]}')

def main():
  args=sys.argv[1:]
  if not args:cmd_chat(None,False,False,False);return
  cmd=args[0];rest=args[1:]
  if cmd=='chat':
   um='--mock'in rest;ua='--auto'in rest;us='--speak'in rest
   rest=[a for a in rest if a not in('--mock','--auto','--speak')]
   cmd_chat(' '.join(rest)if rest else None,um,ua,us);return
  if cmd=='ui':import web;web.main();return
  if cmd=='serve':
   iv=300
   for a in rest:
    if a.startswith('--interval='):
     try:iv=int(a.split('=',1)[1])
     except:pass
   cmd_serve(iv);return
  if cmd=='set-model':cmd_set_model(rest);return
  if cmd=='add-model':cmd_add_model(rest);return
  if cmd=='list-models':cmd_list_models();return
  if cmd=='show-config':cmd_show_config();return
  if cmd=='run-skill':
   if len(rest)<1:print();_p('  Usage: python agent.py run-skill NAME [args-json]',BY);print();return
   cmd_run_skill(rest[0],rest[1]if len(rest)>1 else None);return
  s={'review':cmd_review,'brief':cmd_brief,'notify':cmd_notify,'list-skills':cmd_list_skills,'list-recipes':cmd_list_recipes,'dream':cmd_dream}
  if cmd in s:s[cmd]();return
  
  # If we get here, we might have an agent session that needs cleanup
  try:
    from core import engine
    if hasattr(engine, 'Agent') and 'agent' in dir():
      # Try to shutdown any running agent cleanly
      pass
  except Exception:
    pass
  
  print()
  if UC:print(c(f'  Unknown command: {cmd}',RD))
  else:print(f'Unknown command: {cmd}')
  print_usage()

if __name__=='__main__':main()
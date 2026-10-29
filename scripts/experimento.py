"""Reproducible validation, low-load pilots and an explicitly gated official campaign.
Usage: python scripts/experimento.py {audit,plan,validate,pilot,official,stop}
Official additionally requires --approval-file containing the actual user approval.
All Docker mutations are scoped to Compose project trabalho4-linkextractor.
"""
import argparse
import csv
import ctypes
import datetime as dt
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'configuracoes/campanha.json').read_text(encoding='utf-8'))
PAGES = json.loads((ROOT/'paginas-teste/manifest.json').read_text(encoding='utf-8'))
COMPOSE = ['docker','compose','--project-name','trabalho4-linkextractor','--file',str(ROOT/'docker-compose.yml')]
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORT = {'python':5104,'ruby':5106}


def stamp():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).isoformat()


def save(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def run(args, *, check=True, env=None, timeout=180):
    p = subprocess.run(args,cwd=ROOT,env={**os.environ,**(env or {})},
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
    data=p.stdout
    text=data.decode('utf-16-le' if data.count(b'\x00')>len(data)//5 else 'utf-8',errors='replace')
    if check and p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {args}\n{text}')
    return text.strip()


def compose(*args, **kwargs):
    return run(COMPOSE+list(args),**kwargs)


def get(url):
    try:
        with HTTP.open(url,timeout=12) as response:
            return response.status,{k.title():v for k,v in response.headers.items()},response.read()
    except urllib.error.HTTPError as exc:
        return exc.code,{k.title():v for k,v in exc.headers.items()},exc.read()


def api_get(language,page):
    return get(f'http://127.0.0.1:{PORT[language]}/api/extract?'+urllib.parse.urlencode({'url':page['url']}))


def redis(*args):
    return compose('exec','-T','redis','redis-cli','--raw',*args)


def redis_stats():
    commands=redis('INFO','commandstats')
    stats=redis('INFO','stats')
    result={key:int(re.search(r'^'+key+r':(\d+)',stats,re.M).group(1)) for key in ['keyspace_hits','keyspace_misses']}
    for command in ['get','set']:
        found=re.search(r'cmdstat_'+command+r':calls=(\d+)',commands)
        result[command]=int(found.group(1)) if found else 0
    return result


def keys(language):
    return [f't4:{language}:'+p['url'] for p in PAGES]


def common():
    compose('config','--quiet')
    print(compose('up','-d','--wait','paginas','redis','web'),flush=True)


def select(language,cache):
    compose('stop','api-python','api-ruby')
    compose('up','-d','--no-deps','--force-recreate','--wait','api-'+language,
            env={'CACHE_ENABLED':str(cache).lower()})
    code,_,body=get(f'http://127.0.0.1:{PORT[language]}/health')
    assert code==200 and json.loads(body)['cache_enabled']==cache,body


def verify(directory,scenario,outage=False):
    directory.mkdir(parents=True,exist_ok=True)
    language,cache=scenario['language'],scenario['cache']
    # Only delete our 10 volatile, language-specific keys in our dedicated Redis.
    # Redis save/appendonly are disabled; no persistent experiment data is deleted.
    redis('DEL',*keys(language))
    before=redis_stats()
    rows=[]
    for pass_index in range(2):
        for page in PAGES:
            status,headers,body=get('http://127.0.0.1:8084/'+page['filename'])
            assert status==200 and len(body)==page['size_bytes']
            assert hashlib.sha256(body).hexdigest()==page['sha256']
            status,headers,body=api_get(language,page)
            assert status==200,(status,body)
            assert json.loads(body)==page['expected_links'],(language,page['id'],body)
            expected=('MISS' if pass_index==0 else 'HIT') if cache else 'OFF'
            assert headers.get('X-Cache')==expected,(headers,expected)
            rows.append(dict(language=language,cache=cache,pass_index=pass_index+1,
                page=page['id'],url=page['url'],source_status=200,source_bytes=page['size_bytes'],
                source_sha256=page['sha256'],api_status=status,api_bytes=len(body),
                expected_links=page['expected_count'],actual_links=len(json.loads(body)),
                equivalent_to_manifest=True,cache_header=headers['X-Cache'],
                api_body_sha256=hashlib.sha256(body).hexdigest()))
    after=redis_stats()
    delta={key:after[key]-before[key] for key in before}
    assert delta==({'keyspace_hits':10,'keyspace_misses':10,'get':20,'set':10} if cache else
                   {'keyspace_hits':0,'keyspace_misses':0,'get':0,'set':0}),delta
    if cache:
        assert int(redis('EXISTS',*keys(language)))==10
        for page,key in zip(PAGES,keys(language)):
            assert json.loads(redis('GET',key))==page['expected_links']
    status,_,_=get(f'http://127.0.0.1:{PORT[language]}/api/extract?url=http://invalid/')
    assert status==400
    status,_,body=get(f'http://127.0.0.1:{PORT[language]}/api/'+PAGES[0]['url'])
    assert status==200 and json.loads(body)==PAGES[0]['expected_links']
    status,_,body=get('http://127.0.0.1:8085/?extract=1&api='+language+'&url='+urllib.parse.quote(PAGES[0]['url'],safe=''))
    assert status==200 and '5 links extra'.encode() in body and b'API indispon' not in body
    (directory/'web-demonstracao.html').write_bytes(body)
    outage_result=None
    if outage:
        compose('stop','redis')
        try:
            status,headers,body=api_get(language,PAGES[0])
            assert status==(503 if cache else 200),(status,body)
            if not cache:
                assert headers.get('X-Cache')=='OFF' and json.loads(body)==PAGES[0]['expected_links']
            outage_result={'redis_stopped':True,'http_status':status,'expected_status':503 if cache else 200,'passed':True}
        finally:
            compose('start','--wait','redis')
        if cache:
            for page in PAGES:
                status,headers,body=api_get(language,page)
                assert status==200 and json.loads(body)==page['expected_links']
            for page in PAGES:
                status,headers,body=api_get(language,page)
                assert status==200 and headers.get('X-Cache')=='HIT'
    with (directory/'validacao-urls.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    proof=dict(scenario=scenario,timestamp=stamp(),redis_before=before,redis_after=after,
        redis_delta=delta,cache_keys_verified=10 if cache else 0,redis_outage=outage_result,
        corpus_urls=10,passes=2,all_match_independent_manifest=True,invalid_url_status=400,
        legacy_endpoint_passed=True,php_demo_passed=True)
    save(directory/'validacao.json',proof)
    print(f"VALIDATED {scenario['id']}: 10 URLs, cache {'ON' if cache else 'OFF'}, Redis delta={delta}",flush=True)
    return proof


def host_memory_available():
    if os.name!='nt':return None
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in
            ['totalPhys','availPhys','totalPage','availPage','totalVirtual','availVirtual','availExtended']]
    value=Memory();value.length=ctypes.sizeof(value)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return value.availPhys
    return None


def container_inspect(cid):
    return json.loads(run(['docker','inspect',cid]))[0]


def api_state(language):
    cid=compose('ps','-q','api-'+language)
    x=container_inspect(cid)
    return {'id':cid,'restart_count':x['RestartCount'],'state':x['State'],'image':x['Image'],
            'cpu_quota_nano':x['HostConfig']['NanoCpus'],'memory_bytes':x['HostConfig']['Memory']}


def audit():
    out=ROOT/'documentacao/ambiente';out.mkdir(parents=True,exist_ok=True)
    facts={'recorded_at':stamp(),'git_commit':run(['git','rev-parse','HEAD']),
        'git_version':run(['git','--version']),'docker_version':run(['docker','version']),
        'compose_version':compose('version'),'wsl_version':run(['wsl','--version']),
        'wsl_distributions':run(['wsl','--list','--verbose']),
        'docker_limits':run(['docker','info','--format','CPUs={{.NCPU}} Memory={{.MemTotal}} Kernel={{.KernelVersion}}']),
        'python_host':sys.version,'available_host_memory_bytes':host_memory_available(),
        'external_containers':run(['docker','ps','-a','--format','{{json .}}'])}
    if os.name=='nt':
        facts['hardware']=run(['powershell','-NoProfile','-Command',
            "@{processor=(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);computer=(Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory);os=(Get-CimInstance Win32_OperatingSystem | Select-Object Caption)} | ConvertTo-Json -Depth 4"])
    save(out/'ambiente.json',facts)
    (out/'compose-resolvido.yml').write_text(compose('config'),encoding='utf-8')
    originals=json.loads((ROOT/'documentacao/originais-sha256.json').read_text())
    assert all(hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
    save(out/'originais-verificados.json',dict(checked_at=stamp(),files=len(originals),unchanged=True))
    print('Environment recorded; all 36 original files unchanged.',flush=True)


def plan():
    rng=random.Random(CONFIG['seed']);rows=[]
    for repetition in range(1,CONFIG['repetitions']+1):
        block=[dict(scenario=s['id'],language=s['language'],cache=s['cache'],users=u,repetition=repetition)
            for s in CONFIG['scenarios'] for u in CONFIG['users']]
        rng.shuffle(block)
        rows.extend(block)
    for n,row in enumerate(rows,1):row['order']=n
    target=ROOT/'configuracoes/campanha-planejada.csv'
    with target.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'Plan saved: {len(rows)} sequential runs, seed={CONFIG["seed"]}.')
    return rows


def benchmark(scenario,users,repetition,kind,config):
    name=dt.datetime.now().strftime('%Y%m%d-%H%M%S')+f'-{scenario["id"]}-u{users}-r{repetition}'
    relative=Path('pilotos' if kind=='pilot' else 'oficial/execucoes')/name
    directory=ROOT/'resultados'/relative
    directory.mkdir(parents=True,exist_ok=False)
    select(scenario['language'],scenario['cache'])
    verify(directory/'preflight',scenario,outage=(kind=='pilot'))
    environment={
        'T4_OUTPUT':'/results/'+relative.as_posix(),'T4_RAMP':str(config['ramp_seconds']),
        'T4_MEASURE':str(config['measurement_seconds']),'T4_GRACE':str(config['max_drain_seconds']),
        'T4_WAIT_MIN':str(config['sequence_wait_min']),'T4_WAIT_MAX':str(config['sequence_wait_max']),
        'T4_CALL_WAIT':str(config['invocation_wait_seconds']),'T4_TIMEOUT':str(config['request_timeout_seconds']),
        'T4_MIN_SEQUENCES':str(config['minimum_sequences_per_user']),
        'T4_CACHE':'HIT' if scenario['cache'] else 'OFF','T4_LANGUAGE':scenario['language'],
        'T4_REPETITION':str(repetition),'T4_RUN_ID':name}
    input_paths=[ROOT/'docker-compose.yml',ROOT/'configuracoes/campanha.json',ROOT/'paginas-teste/manifest.json',
        ROOT/'locust/locustfile.py',ROOT/'scripts/experimento.py',ROOT/'scripts/analisar.py']
    for folder in ['api-python','api-ruby','web']:
        input_paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    save(directory/'input-sha256.json',{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in input_paths})
    environment_path=ROOT/'documentacao/ambiente/ambiente.json'
    if environment_path.exists():save(directory/'environment.json',json.loads(environment_path.read_text(encoding='utf-8')))
    save(directory/'parameters.json',dict(scenario=scenario,users=users,repetition=repetition,kind=kind,
        config=config,environment=environment,started_at=stamp()))
    before=api_state(scenario['language']);save(directory/'api-before.json',before)
    redis_before=redis_stats();save(directory/'redis-before.json',redis_before)
    cmd=['run','-d','--no-deps','--name','t4-'+name]
    for k,v in environment.items():cmd.extend(['-e',k+'='+v])
    cmd.extend(['locust','-f','/work/locust/locustfile.py','--headless',
        '--host=http://api-'+scenario['language']+':8080',
        '--users',str(users),'--spawn-rate',str(users/config['ramp_seconds']),
        '--stop-timeout',str(config['max_drain_seconds']),
        '--csv',environment['T4_OUTPUT']+'/locust','--csv-full-history',
        '--logfile',environment['T4_OUTPUT']+'/locust.log','--loglevel','INFO'])
    print(f'START {kind} {name}',flush=True)
    cid=compose(*cmd).splitlines()[-1].strip()
    assert re.fullmatch('[0-9a-f]{64}',cid),cid
    save(directory/'locust-container-start.json',container_inspect(cid))
    start=time.monotonic();emergencies=[];low_memory_streak=0
    maximum=config['ramp_seconds']+config['measurement_seconds']+2*config['max_drain_seconds']+60
    try:
        with (directory/'docker-resources.jsonl').open('w',encoding='utf-8') as f:
            while container_inspect(cid)['State']['Running']:
                sample_time=time.time()
                stats=run(['docker','stats','--no-stream','--format','{{json .}}'],timeout=30)
                memory=host_memory_available()
                row={'timestamp':(sample_time+time.time())/2,'collected_at':stamp(),
                    'host_available_memory_bytes':memory,
                    'containers':[json.loads(line) for line in stats.splitlines() if line.startswith('{')]}
                f.write(json.dumps(row)+'\n');f.flush()
                low_memory_streak=low_memory_streak+1 if memory is not None and memory<384*1024**2 else 0
                if time.monotonic()-start>maximum or low_memory_streak>=3:
                    emergencies.append('Run timeout or host available memory <384 MiB for three samples')
                    run(['docker','stop','--time',str(config['max_drain_seconds']),cid],timeout=config['max_drain_seconds']+30)
                    break
                time.sleep(0.5)
    finally:
        state=container_inspect(cid)
        if state['State']['Running']:
            run(['docker','stop','--time',str(config['max_drain_seconds']),cid],timeout=config['max_drain_seconds']+30)
            state=container_inspect(cid)
        save(directory/'locust-container-end.json',state)
        (directory/'console.log').write_text(run(['docker','logs',cid],check=False),encoding='utf-8')
        (directory/'api.log').write_text(compose('logs','--no-color','api-'+scenario['language']),encoding='utf-8')
        save(directory/'api-after.json',api_state(scenario['language']))
    if not (directory/'summary.json').exists():
        raise RuntimeError(f'No summary produced. Inspect {directory}/console.log')
    summary=json.loads((directory/'summary.json').read_text())
    summary['scenario']=scenario['id'];summary['cache']='ON' if scenario['cache'] else 'OFF'
    summary['kind']=kind;summary['locust_exit_code']=state['State']['ExitCode']
    summary['orchestrator_wall_seconds']=time.monotonic()-start
    after=api_state(scenario['language'])
    if after['restart_count']!=before['restart_count'] or after['state']['OOMKilled']:
        emergencies.append('API restart or OOM during test')
    if not after['state']['Running']:emergencies.append('API exited during test')
    redis_after=redis_stats();save(directory/'redis-after.json',redis_after)
    delta={k:redis_after[k]-redis_before[k] for k in redis_before}
    summary['redis_measurement_and_ramp_delta']=delta
    if scenario['cache']:
        if delta['set'] or delta['keyspace_misses'] or delta['get']<=0:
            emergencies.append('Warm cache did not remain entirely HIT')
    elif any(delta.values()):emergencies.append('Redis used while cache OFF')
    summary['anomaly_reasons'].extend(emergencies)
    summary['valid_for_comparison']=not summary['anomaly_reasons']
    # Independent audit of every completed measured user sequence and native CSV count.
    with (directory/'sequences.csv').open(encoding='utf-8') as f:
        seq=[r for r in csv.DictReader(f) if r['phase']=='measurement']
    assert len(seq)==summary['complete_sequences']
    assert all(int(r['invocations'])==10 and int(r['unique_urls'])==10 for r in seq)
    with (directory/'locust_final_stats.csv').open(encoding='utf-8') as f:
        native=list(csv.DictReader(f))
    total=next(r for r in native if r['Name']=='Aggregated')
    assert int(total['Request Count'])==summary['requests']==10*len(seq)
    assert int(total['Failure Count'])==summary['failures']
    summary['native_csv_audited']=True
    save(directory/'summary.json',summary)
    print('END '+name+': '+json.dumps({k:summary[k] for k in ['requests','failures','complete_sequences',
        'actual_measurement_seconds','mean_ms','p95_ms','rps','valid_for_comparison','anomaly_reasons']}),flush=True)
    if not summary['valid_for_comparison'] or summary['failure_rate']>0.05:
        raise RuntimeError(f'Campaign stopped after anomalous run: {directory}')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['audit','plan','validate','pilot','official','stop'])
    parser.add_argument('--approval-file',type=Path)
    parser.add_argument('--scenario',choices=['A','B','C','D'],help='Restrict a pilot or functional validation only')
    args=parser.parse_args()
    if args.action=='plan':plan();return
    if args.action=='audit':audit();return
    if args.action=='stop':print(compose('stop'));return
    if args.action=='official':
        if args.scenario:parser.error('--scenario is only for pilots/functional validation')
        if not args.approval_file or not args.approval_file.is_file():
            parser.error('Explicit user approval is required. Pass a file with the actual approval text and date.')
        approval=json.loads(args.approval_file.read_text(encoding='utf-8-sig'))
        if approval.get('approved') is not True or not approval.get('user_message') or not approval.get('approved_at'):
            parser.error('Approval file must contain approved=true, approved_at and the real user_message')
        pilot_summaries=list((ROOT/'resultados/pilotos').glob('*/summary.json'))
        passed={json.loads(p.read_text()).get('scenario') for p in pilot_summaries if json.loads(p.read_text()).get('valid_for_comparison') and json.loads(p.read_text()).get('native_csv_audited')}
        if passed!={'A','B','C','D'}:parser.error('All four validated pilot scenarios are required first')
        if (ROOT/'resultados/oficial/aprovacao-utilizada.json').exists():
            parser.error('Campaign already initialized; review existing data before starting another campaign')
        save(ROOT/'resultados/oficial/aprovacao-utilizada.json',approval)
    common()
    try:
        audit()
        if args.action=='validate':
            for s in CONFIG['scenarios']:
                if args.scenario and s['id']!=args.scenario:continue
                select(s['language'],s['cache'])
                verify(ROOT/'resultados/pilotos'/('funcional-'+s['id']),s,outage=True)
        elif args.action=='pilot':
            cfg={**CONFIG,'ramp_seconds':5,'measurement_seconds':20,'recovery_seconds':5}
            for s in CONFIG['scenarios']:
                if args.scenario and s['id']!=args.scenario:continue
                benchmark(s,5,1,'pilot',cfg)
                time.sleep(cfg['recovery_seconds'])
        elif args.action=='official':
            for row in plan():
                s=next(s for s in CONFIG['scenarios'] if s['id']==row['scenario'])
                benchmark(s,row['users'],row['repetition'],'official',CONFIG)
                time.sleep(CONFIG['recovery_seconds'])
    finally:
        # No benchmark or project server remains running after this command finishes.
        print(compose('stop'),flush=True)


if __name__=='__main__':
    main()

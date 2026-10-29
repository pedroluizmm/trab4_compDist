"""Traceable consolidation and metric-based plots. Never blends pilot and official data."""
import argparse
import csv
import hashlib
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'configuracoes/campanha.json').read_text())
METRICS=['requests','successes','failures','failure_rate','mean_ms','median_ms','p90_ms','p95_ms',
    'p99_ms','min_ms','max_ms','rps','success_rps','average_content_bytes','actual_measurement_seconds',
    'complete_sequences','sequences_per_second','locust_cpu_mean_percent','locust_cpu_max_percent',
    'locust_rss_max_bytes','locust_event_loop_lag_p95_ms','api_cpu_mean_percent','api_cpu_max_percent',
    'api_memory_peak_bytes','host_min_available_memory_bytes']
COLORS={'A':'#4777ff','B':'#09bdd5','C':'#aa62ec','D':'#ed71aa'}
LABELS={'A':'Python / OFF','B':'Python / ON','C':'Ruby / OFF','D':'Ruby / ON'}


def save_csv(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8') as f:
        fields=list(dict.fromkeys(k for r in rows for k in r))
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def memory_bytes(text):
    import re
    m=re.match(r'([\d.]+)\s*([a-zA-Z]+)',text)
    if not m:return None
    units={'B':1,'kB':1000,'KB':1000,'MB':1000**2,'GB':1000**3,
           'KiB':1024,'MiB':1024**2,'GiB':1024**3}
    return float(m[1])*units[m[2]]


def resources(directory,s):
    path=directory/'docker-resources.jsonl'
    if not path.exists():return
    lo=s['measurement_start_epoch'];hi=lo+s['actual_measurement_seconds']
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    rows=[r for r in rows if lo<=r['timestamp']<=hi]
    cpus=[];mem=[];host=[]
    for row in rows:
        if row.get('host_available_memory_bytes') is not None:host.append(row['host_available_memory_bytes'])
        for c in row['containers']:
            if c['Name']=='trabalho4-linkextractor-api-'+s['language']+'-1':
                cpus.append(float(c['CPUPerc'].rstrip('%')))
                value=memory_bytes(c['MemUsage'].split('/')[0])
                if value is not None:mem.append(value)
    s['api_cpu_mean_percent']=st.mean(cpus) if cpus else None
    s['api_cpu_max_percent']=max(cpus) if cpus else None
    s['api_memory_peak_bytes']=max(mem) if mem else None
    s['host_min_available_memory_bytes']=min(host) if host else None
    s['docker_resource_samples_in_measurement']=len(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kind',choices=['pilot','official'],required=True)
    args=ap.parse_args()
    base=ROOT/'resultados'/('pilotos' if args.kind=='pilot' else 'oficial')
    source=base if args.kind=='pilot' else base/'execucoes'
    out=base/'consolidado';out.mkdir(parents=True,exist_ok=True)
    charts=base/'graficos';charts.mkdir(parents=True,exist_ok=True)
    runs=[];provenance=[];perpage=[]
    for p in sorted(source.glob('*/summary.json')):
        s=json.loads(p.read_text())
        if s.get('kind')!=args.kind:continue
        resources(p.parent,s)
        s['source_directory']=p.parent.relative_to(ROOT).as_posix()
        s['summary_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        native=p.parent/'locust_final_stats.csv'
        if not native.exists():native=p.parent/'locust_stats.csv'
        s['native_csv_sha256']=hashlib.sha256(native.read_bytes()).hexdigest()
        s['anomaly_reasons']=' | '.join(s['anomaly_reasons'])
        runs.append(s)
        for f in p.parent.rglob('*'):
            if f.is_file():provenance.append({'path':f.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size})
        values=defaultdict(list)
        with (p.parent/'request_samples.csv').open(encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['phase']=='measurement':values[r['page']].append(float(r['response_time_ms']))
        for page,times in values.items():
            perpage.append(dict(run_id=s['run_id'],valid_for_comparison=s['valid_for_comparison'],scenario=s['scenario'],language=s['language'],cache=s['cache'],
                users=s['users'],repetition=s['repetition'],page=page,requests=len(times),mean_ms=st.mean(times)))
    if not runs:raise SystemExit('No measured runs found; no invented results will be generated.')
    scalar=[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in runs]
    save_csv(out/'execucoes.csv',scalar);save_csv(out/'rastreabilidade-sha256.csv',provenance)
    save_csv(out/'por-pagina.csv',perpage)
    valid=[r for r in runs if r['valid_for_comparison']]
    if args.kind=='official':
        actual={(r['scenario'],r['users'],r['repetition']) for r in valid}
        expected={(s['id'],u,rep) for s in CONFIG['scenarios'] for u in CONFIG['users'] for rep in range(1,4)}
        if len(runs)!=36 or actual!=expected or len(actual)!=len(runs):
            raise SystemExit('Consolidated available raw runs, but official analysis requires all 36 unique, valid runs.')
    groups=defaultdict(list)
    for r in valid:groups[(r['scenario'],r['users'])].append(r)
    aggregates=[]
    for (scenario,users),rows in sorted(groups.items()):
        a=dict(scenario=scenario,language=rows[0]['language'],cache=rows[0]['cache'],users=users,repetitions=len(rows))
        for metric in METRICS:
            values=[r[metric] for r in rows if r.get(metric) is not None]
            a[metric+'_mean']=st.mean(values) if values else None
            a[metric+'_sd']=st.stdev(values) if len(values)>=2 else None
        aggregates.append(a)
    save_csv(out/'agregados.csv',aggregates)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,
        'axes.spines.right':False,'figure.facecolor':'white','axes.grid':True,'grid.alpha':0.18})
    subtitle='PILOTOS / 5 usuarios / 1 repeticao; sem inferencia sobre a matriz oficial' if args.kind=='pilot' else '3 repeticoes por ponto / media +/- desvio-padrao entre execucoes'

    def finish(fig,name,title):
        fig.suptitle(title,fontsize=16,fontweight='bold',y=0.98)
        fig.text(0.5,0.02,subtitle,ha='center',fontsize=9,color='#515c71')
        fig.tight_layout(rect=(0,0.06,1,0.94))
        fig.savefig(charts/(name+'.png'),dpi=180,bbox_inches='tight')
        fig.savefig(charts/(name+'.svg'),bbox_inches='tight')
        plt.close(fig)

    def line(ax,metric,label,scenarios=('A','B','C','D')):
        for scenario in scenarios:
            rows=sorted((a for a in aggregates if a['scenario']==scenario),key=lambda a:a['users'])
            if not rows:continue
            scale=100 if metric=='failure_rate' else 1
            x=[a['users'] for a in rows];y=[a[metric+'_mean']*scale for a in rows]
            error=[(a[metric+'_sd'] or 0)*scale for a in rows]
            ax.errorbar(x,y,yerr=error,marker='o',capsize=4,label=LABELS[scenario],color=COLORS[scenario])
        ax.set(xlabel='Usuarios virtuais',ylabel=label)
        ax.set_xticks(sorted({a['users'] for a in aggregates}))
        ax.legend(fontsize=9);ax.set_ylim(bottom=0)

    if args.kind=='pilot':
        fig,axes=plt.subplots(1,2,figsize=(11,4.8))
        for ax,metric,label in [(axes[0],'mean_ms','Tempo medio (ms)'),(axes[1],'rps','Requisicoes / segundo')]:
            rows=sorted(aggregates,key=lambda a:a['scenario'])
            ax.bar([LABELS[a['scenario']] for a in rows],[a[metric+'_mean'] for a in rows],color=[COLORS[a['scenario']] for a in rows])
            ax.set_ylabel(label);ax.tick_params(axis='x',rotation=15)
        finish(fig,'pilotos-latencia-vazao','Validacao de baixa carga: resultados exploratorios')
    else:
        for metric,label,title in [
            ('mean_ms','Tempo medio (ms)','Tempo medio por quantidade de usuarios'),
            ('median_ms','Media das medianas (ms)','Mediana por quantidade de usuarios'),
            ('p95_ms','Media dos P95 (ms)','P95 por quantidade de usuarios'),
            ('p99_ms','Media dos P99 (ms)','P99 por quantidade de usuarios'),
            ('rps','Requisicoes / segundo','Vazao total por quantidade de usuarios'),
            ('failure_rate','Requisicoes com falha (%)','Taxa de falhas por quantidade de usuarios'),
            ('success_rps','Requisicoes bem-sucedidas / segundo','Vazao sem falhas por quantidade de usuarios')]:
            fig,ax=plt.subplots(figsize=(9,5.2));line(ax,metric,label);finish(fig,metric,title)
        for name,scenarios,title in [
            ('python-ruby-off',('A','C'),'Python x Ruby / cache OFF'),
            ('python-ruby-on',('B','D'),'Python x Ruby / cache ON aquecido'),
            ('cache-python',('A','B'),'Python / cache ON x OFF'),
            ('cache-ruby',('C','D'),'Ruby / cache ON x OFF')]:
            fig,axes=plt.subplots(1,3,figsize=(14,4.8))
            for ax,metric,label in zip(axes,['mean_ms','p95_ms','rps'],['Tempo medio (ms)','Media P95 (ms)','Requisicoes / s']):line(ax,metric,label,scenarios)
            finish(fig,name,title)
        lookup={(r['language'],r['users'],r['repetition'],r['cache']):r for r in valid}
        gains=[]
        for language in ['python','ruby']:
            for u in CONFIG['users']:
                for rep in range(1,4):
                    off=lookup[(language,u,rep,'OFF')];on=lookup[(language,u,rep,'ON')]
                    gains.append(dict(language=language,users=u,repetition=rep,
                        latency_reduction_percent=100*(off['mean_ms']-on['mean_ms'])/off['mean_ms'],
                        rps_increase_percent=100*(on['rps']-off['rps'])/off['rps']))
        save_csv(out/'ganho-cache-por-repeticao.csv',gains)
        fig,axes=plt.subplots(1,2,figsize=(11,5))
        for ax,key,label in zip(axes,['latency_reduction_percent','rps_increase_percent'],['Reducao de latencia media (%)','Aumento de RPS (%)']):
            for language,color in [('python',COLORS['A']),('ruby',COLORS['C'])]:
                vals=[[r[key] for r in gains if r['language']==language and r['users']==u] for u in CONFIG['users']]
                ax.errorbar(CONFIG['users'],[st.mean(v) for v in vals],yerr=[st.stdev(v) for v in vals],marker='o',capsize=4,color=color,label=language.title())
            ax.axhline(0,color='gray',lw=1);ax.set(xlabel='Usuarios virtuais',ylabel=label);ax.legend()
        finish(fig,'ganho-cache','Ganho do cache / pares da mesma repeticao')
    print(f'{len(runs)} real runs consolidated; {len(list(charts.glob("*.png")))} charts in {charts}')


if __name__=='__main__':main()

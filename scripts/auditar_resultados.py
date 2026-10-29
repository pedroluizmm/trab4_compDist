"""Independent offline audit of raw measured samples, sequences and final native CSVs."""
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
reports=[]
for p in sorted((ROOT/'resultados/pilotos').glob('*/summary.json')):
    s=json.loads(p.read_text())
    if not s.get('valid_for_comparison'):continue
    with (p.parent/'request_samples.csv').open(encoding='utf-8') as f:
        calls=[r for r in csv.DictReader(f) if r['phase']=='measurement']
    with (p.parent/'sequences.csv').open(encoding='utf-8') as f:
        seq=[r for r in csv.DictReader(f) if r['phase']=='measurement']
    by_sequence=defaultdict(list)
    for r in calls:by_sequence[(r['user'],r['sequence'])].append(r)
    assert len(calls)==s['requests']==10*len(seq)
    assert len(by_sequence)==len(seq)==s['complete_sequences']
    expected_pages={f'pagina{i:02d}' for i in range(1,11)}
    assert all(len(rows)==10 and {r['page'] for r in rows}==expected_pages for rows in by_sequence.values())
    assert {(r['user'],r['sequence']) for r in seq}==set(by_sequence)
    per_user=Counter(r['user'] for r in seq)
    assert len(per_user)==s['users'] and min(per_user.values())>=3
    assert sum(r['success']=='0' for r in calls)==s['failures']
    assert all(r['cache']==('HIT' if s['cache']=='ON' else 'OFF') for r in calls)
    assert math.isclose(sum(float(r['response_time_ms']) for r in calls)/len(calls),s['mean_ms'],rel_tol=1e-12)
    assert math.isclose(sum(int(r['response_bytes']) for r in calls)/len(calls),s['average_content_bytes'],rel_tol=1e-12)
    with (p.parent/'locust_final_stats.csv').open(encoding='utf-8') as f:
        total=next(r for r in csv.DictReader(f) if r['Name']=='Aggregated')
    assert int(total['Request Count'])==len(calls)
    assert int(total['Failure Count'])==s['failures']
    assert math.isclose(float(total['Average Response Time']),s['mean_ms'],rel_tol=1e-12)
    assert float(total['95%'])==s['p95_ms'] and float(total['99%'])==s['p99_ms']
    assert math.isclose(s['rps'],len(calls)/s['actual_measurement_seconds'],rel_tol=1e-12)
    before=json.loads((p.parent/'api-before.json').read_text())
    after=json.loads((p.parent/'api-after.json').read_text())
    assert before['id']==after['id'] and before['restart_count']==after['restart_count']
    assert not after['state']['OOMKilled']
    reports.append(dict(run_id=s['run_id'],scenario=s['scenario'],calls=len(calls),sequences=len(seq),
        users=len(per_user),minimum_sequences_per_user=min(per_user.values()),all_ten_unique_urls=True,
        raw_mean_matches=True,native_csv_matches=True,cache_headers_match=True,no_restart_or_oom=True))
assert {r['scenario'] for r in reports}=={'A','B','C','D'},reports
originals=json.loads((ROOT/'documentacao/originais-sha256.json').read_text())
assert all(hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
result=dict(passed=True,original_files_unchanged=len(originals),runs=reports)
(ROOT/'documentacao/auditoria-resultados-pilotos.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))

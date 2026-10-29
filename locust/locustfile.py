"""One task = ten distinct, sequential API calls. See documentacao/METODOLOGIA.md.

No --run-time: the controller owns ramp, sequence barrier, measurement and drain.
Native Locust CSVs are reset at the barrier. Samples retain explicit phase labels.
Only single-process mode is supported; distributed mode requires another protocol.
"""
import csv
import json
import logging
import os
import random
import time
from collections import Counter
from pathlib import Path

import gevent
import psutil
from locust import HttpUser, constant, events, task
from locust.stats import StatsCSV, PERCENTILES_TO_REPORT

ROOT = Path(__file__).resolve().parents[1]
PAGES = json.loads((ROOT / 'paginas-teste/manifest.json').read_text(encoding='utf-8'))
RAMP = float(os.getenv('T4_RAMP', '30'))
MEASURE = float(os.getenv('T4_MEASURE', '120'))
GRACE = float(os.getenv('T4_GRACE', '110'))
WAIT_MIN = float(os.getenv('T4_WAIT_MIN', '1'))
WAIT_MAX = float(os.getenv('T4_WAIT_MAX', '2'))
CALL_WAIT = float(os.getenv('T4_CALL_WAIT', '0'))
TIMEOUT = float(os.getenv('T4_TIMEOUT', '10'))
MIN_SEQUENCES = int(os.getenv('T4_MIN_SEQUENCES', '3'))
CACHE_EXPECTED = os.getenv('T4_CACHE', 'OFF')
OUTPUT = Path(os.getenv('T4_OUTPUT', '/results/pilotos/manual'))
S = {'phase': 'idle', 'users': {}, 'parked': set(), 'sequence_counts': Counter(),
     'page_counts': Counter(), 'errors': [], 'resources': [], 'seq_total': 0,
     'sample_total': 0, 'sample_failures': 0, 'last_end': 0.0, 'files': []}


def writer(filename, fields):
    f = (OUTPUT / filename).open('w', newline='', encoding='utf-8')
    S['files'].append(f)
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    return w


def cgroup_cpu():
    try:
        return dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())
    except OSError:
        return {}


@events.request.add_listener
def sample(request_type, name, response_time, response_length, exception, context=None, **kwargs):
    c = context or {}
    if 'phase' not in c or 'samples' not in S:
        return
    S['samples'].writerow(dict(timestamp=time.time(), phase=c['phase'],
        user=c['user'], sequence=c['sequence'], page=name,
        response_time_ms=response_time, response_bytes=response_length,
        success=int(exception is None), error=str(exception or ''), cache=c.get('cache', '')))
    if c['phase'] == 'measurement':
        S['sample_total'] += 1
        S['sample_failures'] += int(exception is not None)
        S['page_counts'][name] += 1


class ExtractorUser(HttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.uid = len(S['users']) + 1
        self.sequence = 0
        self.rng = random.Random(20261029 + self.uid)
        S['users'][self.uid] = self

    @task
    def ten_distinct_urls(self):
        phase = S['phase']
        if phase != 'ramp' and phase != 'measurement':
            S['parked'].add(self.uid)
            gevent.sleep(0.02)
            return
        S['parked'].discard(self.uid)
        self.sequence += 1
        started = time.perf_counter()
        failures = 0
        for page in PAGES:
            context = dict(phase=phase, user=self.uid, sequence=self.sequence)
            with self.client.get('/api/extract', params={'url': page['url']},
                    name=page['id'], timeout=TIMEOUT, catch_response=True, context=context) as response:
                context['cache'] = response.headers.get('X-Cache', '')
                # HttpSession copies the supplied context; update the emitted metadata.
                response.request_meta['context']['cache'] = context['cache']
                error = None
                if response.status_code != 200:
                    error = f'HTTP {response.status_code}'
                else:
                    try:
                        actual = response.json()
                        if not isinstance(actual, list) or actual != page['expected_links']:
                            error = 'Extraction differs from independent manifest'
                        elif context['cache'] != CACHE_EXPECTED:
                            error = f"Cache expected {CACHE_EXPECTED}, received {context['cache']}"
                    except (ValueError, TypeError):
                        error = 'Invalid JSON'
                if error:
                    response.failure(error)
                    failures += 1
            if CALL_WAIT:
                gevent.sleep(CALL_WAIT)
        finished = time.perf_counter()
        S['sequences'].writerow(dict(phase=phase, user=self.uid, sequence=self.sequence,
            unique_urls=len(PAGES), invocations=len(PAGES), failures=failures,
            elapsed_seconds=finished-started))
        if phase == 'measurement':
            S['seq_total'] += 1
            S['sequence_counts'][self.uid] += 1
            S['last_end'] = finished
        # Think time is between complete sequences; it is interruptible at a phase boundary.
        wait_until = time.perf_counter() + self.rng.uniform(WAIT_MIN, WAIT_MAX)
        while S['phase'] == phase and time.perf_counter() < wait_until:
            gevent.sleep(min(0.05, max(0, wait_until-time.perf_counter())))


def monitor(environment):
    process = psutil.Process()
    process.cpu_percent()
    while S['phase'] not in ('finished', 'idle'):
        expected = time.perf_counter() + 1
        gevent.sleep(1)
        if S['phase'] == 'finished':
            break
        row = dict(timestamp=time.time(), phase=S['phase'],
            cpu_process_percent=process.cpu_percent(), rss_bytes=process.memory_info().rss,
            event_loop_lag_ms=max(0, (time.perf_counter()-expected)*1000),
            cgroup_throttled_usec=cgroup_cpu().get('throttled_usec', ''),
            users=environment.runner.user_count)
        S['resource_writer'].writerow(row)
        S['resources'].append(row)
        for f in S['files']:
            f.flush()


def all_parked(environment, limit):
    deadline = time.perf_counter() + limit
    expected = environment.parsed_options.num_users
    while len(S['parked']) < expected or environment.runner.user_count != expected:
        if time.perf_counter() > deadline:
            raise RuntimeError('Users did not reach complete-sequence barrier within deadline')
        gevent.sleep(0.02)


def controller(environment):
    try:
        gevent.sleep(RAMP)
        S['phase'] = 'arming'
        all_parked(environment, GRACE)
        environment.stats.reset_all()
        S['measurement_epoch'] = time.time()
        S['measurement_start'] = time.perf_counter()
        S['last_end'] = S['measurement_start']
        S['phase'] = 'measurement'
        logging.info('T4_MEASUREMENT_START all users at sequence boundary')
        gevent.sleep(MEASURE)
        S['phase'] = 'draining'
        all_parked(environment, GRACE)
        S['measurement_end'] = max(S['measurement_start']+MEASURE, S['last_end'])
        logging.info('T4_MEASUREMENT_END all sequences complete')
    except Exception as exc:
        S['errors'].append(str(exc))
        logging.exception('T4 controller failed')
    finally:
        S['phase'] = 'finished'
        environment.runner.quit()


@events.test_start.add_listener
def start(environment, **kwargs):
    if environment.parsed_options.master or environment.parsed_options.worker:
        raise RuntimeError('This barrier implementation requires one local Locust process')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    S['samples'] = writer('request_samples.csv', ['timestamp','phase','user','sequence','page',
        'response_time_ms','response_bytes','success','error','cache'])
    S['sequences'] = writer('sequences.csv', ['phase','user','sequence','unique_urls',
        'invocations','failures','elapsed_seconds'])
    S['resource_writer'] = writer('locust_resources.csv', ['timestamp','phase','cpu_process_percent',
        'rss_bytes','event_loop_lag_ms','cgroup_throttled_usec','users'])
    S['run_start'] = time.perf_counter()
    S['phase'] = 'ramp'
    gevent.spawn(monitor, environment)
    gevent.spawn(controller, environment)


@events.test_stop.add_listener
def stop(environment, **kwargs):
    S['phase'] = 'finished'
    total = environment.stats.total
    duration = S.get('measurement_end', time.perf_counter())-S.get('measurement_start', time.perf_counter())
    reasons = list(S['errors'])
    expected_users = environment.parsed_options.num_users
    if 'measurement_end' not in S:
        reasons.append('Measurement did not finish normally')
    if len(S['sequence_counts']) != expected_users or any(
            S['sequence_counts'][uid] < MIN_SEQUENCES for uid in S['users']):
        reasons.append('Insufficient complete measured sequences per user')
    if S['sample_total'] != S['seq_total']*10 or total.num_requests != S['sample_total']:
        reasons.append('Measured samples do not equal ten times complete sequences')
    if len(S['page_counts']) != 10 or len(set(S['page_counts'].values())) != 1:
        reasons.append('Unbalanced URL coverage')
    if duration > MEASURE+max(5, MEASURE*0.05):
        reasons.append('Long drain: actual duration differs materially from planned window')
    resources = [r for r in S['resources'] if r['phase']=='measurement']
    cpus = [r['cpu_process_percent'] for r in resources]
    lags = sorted(r['event_loop_lag_ms'] for r in resources)
    high_cpu_streak = longest_streak = 0
    for cpu in cpus:
        high_cpu_streak = high_cpu_streak+1 if cpu >= 85 else 0
        longest_streak = max(longest_streak, high_cpu_streak)
    if longest_streak >= 5:
        reasons.append('Load generator CPU >=85% of one core for five samples')
    lag95 = lags[min(len(lags)-1, int(len(lags)*0.95))] if lags else None
    if lag95 is not None and lag95 > 100:
        reasons.append('Load generator event loop p95 lag >100 ms')
    row = dict(valid_for_comparison=not reasons, anomaly_reasons=reasons,
        language=os.getenv('T4_LANGUAGE'), cache=os.getenv('T4_CACHE'),
        users=expected_users, repetition=int(os.getenv('T4_REPETITION','1')),
        run_id=os.getenv('T4_RUN_ID'), measurement_start_epoch=S.get('measurement_epoch'),
        planned_ramp_seconds=RAMP, planned_measurement_seconds=MEASURE,
        actual_measurement_seconds=duration, whole_process_seconds=time.perf_counter()-S['run_start'],
        requests=total.num_requests, failures=total.num_failures,
        successes=total.num_requests-total.num_failures, failure_rate=total.fail_ratio,
        mean_ms=total.avg_response_time, median_ms=total.median_response_time,
        p90_ms=total.get_response_time_percentile(0.90),
        p95_ms=total.get_response_time_percentile(0.95),p99_ms=total.get_response_time_percentile(0.99),
        min_ms=total.min_response_time,max_ms=total.max_response_time,
        rps=total.num_requests/duration if duration>0 else None,
        success_rps=(total.num_requests-total.num_failures)/duration if duration>0 else None,
        average_content_bytes=total.avg_content_length,
        complete_sequences=S['seq_total'], sequences_per_second=S['seq_total']/duration if duration>0 else None,
        measured_sequences_per_user=dict(S['sequence_counts']), measured_calls_per_page=dict(S['page_counts']),
        locust_cpu_mean_percent=sum(cpus)/len(cpus) if cpus else None,
        locust_cpu_max_percent=max(cpus) if cpus else None, locust_event_loop_lag_p95_ms=lag95,
        locust_rss_max_bytes=max((r['rss_bytes'] for r in resources),default=None),
        wait_min_seconds=WAIT_MIN,wait_max_seconds=WAIT_MAX,invocation_wait_seconds=CALL_WAIT,
        percentile_method='Locust rounded response-time histogram; no pooling of repetition percentiles')
    (OUTPUT/'summary.json').write_text(json.dumps(row,indent=2)+'\n',encoding='utf-8')
    # The periodic exporter can lag behind the last sequence. Preserve it and
    # produce a final snapshot using the same native Locust serializer.
    final_csv = StatsCSV(environment, PERCENTILES_TO_REPORT)
    for filename, method in [('locust_final_stats.csv', final_csv.requests_csv),
                             ('locust_final_failures.csv', final_csv.failures_csv),
                             ('locust_final_exceptions.csv', final_csv.exceptions_csv)]:
        with (OUTPUT/filename).open('w', newline='', encoding='utf-8') as f:
            method(csv.writer(f))
    for f in S['files']:
        f.flush(); f.close()
    environment.process_exit_code = 2 if reasons else (1 if total.num_failures else 0)

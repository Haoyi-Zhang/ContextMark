"""Executable audits for the final-round proof and carrier corrections."""
from __future__ import annotations
from copy import deepcopy
from itertools import combinations, product
from unittest.mock import patch
import math, statistics, time
from . import threshold_backend as tb
from .compiler import make_demo_program
from .bounds import first_hit_probability, fixed_schedule_product, survival_weighted_certificate


def assurance_checks():
    k=b'r'*32; payload=b'p'*32
    issued=tb.mark(k,make_demo_program(8),payload,n=5,t=3)
    closure=[]
    for bits in product([0,1],repeat=5):
        x=deepcopy(issued); retained=[c for c,b in zip(x[tb.CARRIER_FIELD],bits) if b]
        for noise in ['none','repeat','junk','both']:
            x[tb.CARRIER_FIELD]=deepcopy(retained)
            if noise in ('repeat','both'): x[tb.CARRIER_FIELD]+=deepcopy(retained)
            if noise in ('junk','both'): x[tb.CARRIER_FIELD]+=[None,{'noise':'unauthenticated'}]
            found=tb.read(k,x)==payload; authorized=tb.public_authorized_derivative(issued,x,threshold=3)
            closure.append({'mask':''.join(map(str,bits)),'noise':noise,'read_success':found,'authorized':authorized,'expected':sum(bits)>=3,'passed':found==authorized==(sum(bits)>=3)})
    assignments=0; mismatches=0
    with patch.object(tb,'P',7):
        for t in [2,3]:
            for values in product(range(7),repeat=4):
                points=list(zip(range(1,5),values)); basis=points[:t]; w=tb._interpolation_weights(basis)
                secret=tb._evaluate_interpolant(basis,w,0)
                residual=all(tb._evaluate_interpolant(basis,w,x)==y for x,y in points[t:])
                legacy=all(tb._interpolate(list(q))==secret for q in combinations(points,t))
                assignments+=1;mismatches+=residual!=legacy
    supported=[]
    for n in range(2,33):
        for t in range(2,n+1):
            x=tb.mark(k,make_demo_program(2),payload,n=n,t=t)
            supported.append({'n':n,'t':t,'passed':tb.read(k,x)==payload})
    timing=[]
    for n,t in [(5,3),(10,5),(32,16)]:
        x=tb.mark(k,make_demo_program(8),payload,n=n,t=t)
        new_times=[]; old_times=[]
        for _ in range(31):
            start=time.perf_counter_ns(); assert tb.read(k,x)==payload
            new_times.append((time.perf_counter_ns()-start)/1000)
            if n<=10:
                start=time.perf_counter_ns(); cs=tb._valid_carriers(k,x)
                points=[(c['index'],int(c['value'],16)) for c in cs]
                old=all(tb._interpolate(list(q))==int.from_bytes(payload,'big') for q in combinations(points,t))
                assert old
                old_times.append((time.perf_counter_ns()-start)/1000)
        timing.append({'n':n,'t':t,'runs':31,'legacy_subsets':math.comb(n,t),'residual_points':n-t,'residual_read_median_us':statistics.median(new_times),'legacy_subset_read_median_us':statistics.median(old_times) if old_times else None,'legacy_timing_status':'measured' if old_times else 'not_run_declared_combinatorial_boundary'})
    product_case={'actual_hazards':[0.0,0.0],'upper_hazards':[0.5,0.5],'actual_first_hit':first_hit_probability([0,0]),'upper_certificate':survival_weighted_certificate([0,0],[.5,.5]),'product_probability_bound':fixed_schedule_product([.5,.5])}
    result={'schema':'tdsc-assurance-checks','closure_rows':closure,'closure_count':len(closure),'closure_all_passed':all(r['passed'] for r in closure),'small_field_assignments':assignments,'polynomial_equivalence_mismatches':mismatches,'threshold_parameter_pairs':supported,'threshold_pair_count':len(supported),'threshold_pairs_all_passed':all(r['passed'] for r in supported),'reader_timing':timing,'product_certificate_counterexample':product_case}
    result['passed']=result['closure_all_passed'] and not mismatches and result['threshold_pairs_all_passed']
    return result

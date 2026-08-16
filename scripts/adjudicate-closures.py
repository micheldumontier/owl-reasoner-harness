#!/usr/bin/env python3
"""Adjudicate rustdl vs Konclude using HermiT as the third opinion.

PARSER NOTE: Konclude writes OWL/XML (.owx, `<SubClassOf>...`); HermiT via robot's
CommandLine writes FUNCTIONAL syntax (`SubClassOf( <a> <b> )`). Assuming one format
for both silently yields an empty closure -- which reads as "the reasoner found
nothing" rather than "the parser matched nothing". That happened here.
"""
import re, sys, itertools, collections
TOP='http://www.w3.org/2002/07/owl#Thing'; BOT='http://www.w3.org/2002/07/owl#Nothing'
def close(adj):
    out={}
    for s in adj:
        seen=set(); st=[s]
        while st:
            x=st.pop()
            for y in adj.get(x,()):
                if y not in seen: seen.add(y); st.append(y)
        out[s]={y for y in seen if y not in (TOP,BOT) and y!=s}
    return out
def parse_owx(p):
    t=open(p,errors='replace').read(); adj=collections.defaultdict(set)
    ir=lambda b:[x or y for x,y in re.findall(r'IRI="([^"]+)"|abbreviatedIRI="([^"]+)"',b)]
    for b in re.findall(r'<SubClassOf>(.*?)</SubClassOf>',t,re.S):
        g=ir(b)
        if len(g)==2: adj[g[0]].add(g[1])
    for b in re.findall(r'<EquivalentClasses>(.*?)</EquivalentClasses>',t,re.S):
        for a,c in itertools.permutations(ir(b),2): adj[a].add(c)
    return close(adj)
def parse_ofn(p):
    t=open(p,errors='replace').read(); adj=collections.defaultdict(set)
    for m in re.finditer(r'SubClassOf\(\s*<([^>]+)>\s*<([^>]+)>\s*\)', t):
        adj[m.group(1)].add(m.group(2))
    for m in re.finditer(r'EquivalentClasses\(([^)]*)\)', t):
        g=re.findall(r'<([^>]+)>', m.group(1))
        for a,c in itertools.permutations(g,2): adj[a].add(c)
    return close(adj)
